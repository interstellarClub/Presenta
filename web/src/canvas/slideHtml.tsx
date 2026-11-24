import { renderToStaticMarkup } from "react-dom/server";

import { LayoutView, SLIDE_CSS } from "@/canvas/layouts";
import { buildTypographyCss } from "@/themes/fontStack";
import { themeTokens, tokenVarsCss } from "@/themes/theme";
import type { Slide, ThemeManifest } from "@/types";

interface BuildOptions {
  slide: Slide;
  theme: ThemeManifest | null;
  documentId: string | null;
  selectedSlot?: string | null;
  interactive?: boolean;
  step?: number;
}

export function buildSlideDocument({
  slide,
  theme,
  documentId,
  selectedSlot = null,
  interactive = true,
  step,
}: BuildOptions): string {
  const tokens = themeTokens(theme);
  const styleRules = slide.elements
    .filter(
      (element) =>
        Object.keys(element.styleOverride ?? {}).length > 0 || element.layout !== null,
    )
    .map((element) => {
      const declarations = Object.entries(element.styleOverride)
        .filter(([, value]) => !/[<>;{}]|url\(/i.test(String(value)))
        .map(([key, value]) => `${key.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}: ${value};`)
        .join("");
      const layout = element.layout
        ? `position:absolute;left:${(element.layout.x / 12) * 100}%;top:${element.layout.y}%;` +
          `width:${(element.layout.w / 12) * 100}%;height:${element.layout.h}%;`
        : "";
      return declarations || layout
        ? `.slide-root [data-slot="${element.slotPath}"] { ${layout}${declarations} }`
        : "";
    })
    .join("\n");

  const markup = renderToStaticMarkup(
    <div className="stage slide-root">
      {slide.degraded ? <span className="degraded-flag">degraded</span> : null}
      <LayoutView slide={slide} tokens={tokens} documentId={documentId} selected={selectedSlot} />
    </div>,
  );

  const bridgeEnabled = interactive || step !== undefined;
  const bridge = bridgeEnabled
    ? `<script>
(function () {
  var slideId = ${JSON.stringify(slide.id)};
  var interactive = ${JSON.stringify(interactive)};
  var initialStep = ${JSON.stringify(step ?? null)};
  function notify(payload) { try { parent.postMessage(payload, "*"); } catch (e) {} }
  function applyStep(step) {
    var fragments = Array.prototype.slice.call(document.querySelectorAll("[data-fragment]"));
    fragments.forEach(function (node, index) {
      node.style.opacity = index < step ? "1" : "0";
      node.style.transition = "opacity 0.3s ease";
    });
  }
  var dragging = null;
  document.addEventListener("pointerdown", function (event) {
    if (!interactive) return;
    var el = event.target && event.target.closest ? event.target.closest("[data-slot]") : null;
    if (!el) return;
    var rect = el.getBoundingClientRect();
    dragging = {
      slotPath: el.getAttribute("data-slot"),
      startX: event.clientX,
      startY: event.clientY,
      rect: rect,
      moved: false
    };
  });
  document.addEventListener("pointermove", function (event) {
    if (!dragging || !interactive) return;
    if (Math.abs(event.clientX - dragging.startX) > 3 || Math.abs(event.clientY - dragging.startY) > 3) {
      dragging.moved = true;
    }
  });
  document.addEventListener("pointerup", function (event) {
    if (!dragging || !interactive) return;
    var item = dragging;
    dragging = null;
    if (!item.moved) return;
    var dx = event.clientX - item.startX;
    var dy = event.clientY - item.startY;
    var left = Math.max(0, Math.min(window.innerWidth, item.rect.left + dx));
    var top = Math.max(0, Math.min(window.innerHeight, item.rect.top + dy));
    var width = Math.min(window.innerWidth - left, item.rect.width);
    var height = Math.min(window.innerHeight - top, item.rect.height);
    notify({
      type: "presenta:drag",
      slideId: slideId,
      slotPath: item.slotPath,
      layout: {
        x: Number(((left / window.innerWidth) * 12).toFixed(3)),
        y: Number(((top / window.innerHeight) * 100).toFixed(3)),
        w: Number(((width / window.innerWidth) * 12).toFixed(3)),
        h: Number(((height / window.innerHeight) * 100).toFixed(3))
      }
    });
  });
  if (interactive) {
    document.addEventListener("click", function (event) {
      var el = event.target && event.target.closest ? event.target.closest("[data-slot]") : null;
      if (el) {
        event.stopPropagation();
        notify({ type: "presenta:select", slideId: slideId, slotPath: el.getAttribute("data-slot") });
      }
    }, true);
    document.addEventListener("mouseover", function (event) {
      var el = event.target && event.target.closest ? event.target.closest("[data-slot]") : null;
      if (el) notify({ type: "presenta:hover", slotPath: el.getAttribute("data-slot") });
    }, true);
  }
  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.type === "presenta:step" && data.slideId === slideId && typeof data.step === "number") {
      applyStep(data.step);
    }
  });
  if (typeof initialStep === "number") applyStep(initialStep);
})();
</script>`
    : "";

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
${tokenVarsCss(tokens)}
${buildTypographyCss()}
${SLIDE_CSS}
${styleRules}
</style>
</head>
<body style="margin:0">${markup}${bridge}</body>
</html>`;
}
