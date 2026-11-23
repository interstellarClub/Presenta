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
}

export function buildSlideDocument({
  slide,
  theme,
  documentId,
  selectedSlot = null,
  interactive = true,
}: BuildOptions): string {
  const tokens = themeTokens(theme);
  const styleRules = slide.elements
    .filter((element) => Object.keys(element.styleOverride ?? {}).length > 0)
    .map((element) => {
      const declarations = Object.entries(element.styleOverride)
        .filter(([, value]) => !/[<>;{}]|url\(/i.test(String(value)))
        .map(([key, value]) => `${key.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}: ${value};`)
        .join("");
      return declarations ? `[data-slot="${element.slotPath}"] { ${declarations} }` : "";
    })
    .join("\n");

  const markup = renderToStaticMarkup(
    <div className="stage">
      {slide.degraded ? <span className="degraded-flag">degraded</span> : null}
      <LayoutView slide={slide} tokens={tokens} documentId={documentId} selected={selectedSlot} />
    </div>,
  );

  const bridge = interactive
    ? `<script>
(function () {
  var slideId = ${JSON.stringify(slide.id)};
  function notify(payload) { try { parent.postMessage(payload, "*"); } catch (e) {} }
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
