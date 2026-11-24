import html
import json
from typing import Any

from app.api.schemas.deck import Deck
from app.services.export.layouts_html import render_slide_html, slide_styles

_STANDALONE_SCRIPT = """
(function () {
  var deck = JSON.parse(document.getElementById("presenta-deck").textContent);
  var slides = Array.prototype.slice.call(document.querySelectorAll(".presenta-slide"));
  var current = 0;
  var step = 0;
  function clamp() {
    current = Math.max(0, Math.min(slides.length - 1, current));
    step = 0;
  }
  function paint() {
    slides.forEach(function (slide, index) {
      slide.classList.toggle("is-active", index === current);
    });
    var bar = document.getElementById("presenta-progress");
    if (bar) bar.textContent = (current + 1) + " / " + slides.length;
    if (window.location.hash !== "#" + (current + 1)) {
      history.replaceState(null, "", "#" + (current + 1));
    }
  }
  function next() {
    var active = slides[current];
    var fragments = active ? Array.prototype.slice.call(active.querySelectorAll("[data-fragment]")) : [];
    if (step < fragments.length) {
      fragments[step].classList.add("is-fragment-visible");
      step += 1;
    } else if (current < slides.length - 1) {
      current += 1;
      step = 0;
      paint();
    }
  }
  function prev() {
    if (step > 0) {
      step -= 1;
      var active = slides[current];
      var fragments = active ? Array.prototype.slice.call(active.querySelectorAll("[data-fragment]")) : [];
      fragments.forEach(function (node, index) { node.classList.toggle("is-fragment-visible", index < step); });
    } else if (current > 0) {
      current -= 1;
      step = 0;
      paint();
    }
  }
  document.addEventListener("keydown", function (event) {
    if (["ArrowRight", " ", "PageDown"].indexOf(event.key) >= 0) { event.preventDefault(); next(); }
    else if (["ArrowLeft", "PageUp"].indexOf(event.key) >= 0) { event.preventDefault(); prev(); }
    else if (event.key.toLowerCase() === "f") { document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); }
  });
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest(".presenta-next")) next();
    else if (event.target.closest && event.target.closest(".presenta-prev")) prev();
    else next();
  });
  var initial = parseInt((window.location.hash || "#1").slice(1), 10);
  if (!isNaN(initial)) current = initial - 1;
  clamp();
  paint();
})();
"""


def _theme_css(manifest: dict[str, Any]) -> str:
    variables = (manifest.get("tokens") or {}).get("cssVariables") or {}
    declarations = "\n".join(f"  {name}: {value};" for name, value in variables.items() if name.startswith("--"))
    typography = manifest.get("typography") or {}
    return f"""
:root {{
  {declarations}
  --cjk-scale: 1.03;
  --line-height-cjk: {typography.get('lineHeightCJK', 1.75)};
  --line-height-mixed: {typography.get('lineHeightBody', 1.65)};
  --line-height-heading: {typography.get('lineHeightHeading', 1.25)};
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #0a0b10; }}
body {{
  font-family: var(--font-body, sans-serif);
  color: var(--color-text);
  text-autospace: normal;
  line-break: strict;
  word-break: normal;
  overflow-wrap: anywhere;
}}
.presenta-viewer {{ width: 100vw; height: 100vh; display: grid; place-items: center; }}
.presenta-slide {{ display: none; width: 1280px; height: 720px; background: var(--color-bg); }}
.presenta-slide.is-active {{ display: block; }}
.presenta-controls {{ position: fixed; left: 24px; bottom: 20px; display: flex; gap: 10px; align-items: center; font-size: 13px; color: #9a978f; z-index: 9; }}
.presenta-controls button {{ background: rgba(255,255,255,0.08); color: #e9e6df; border: 1px solid rgba(255,255,255,0.16); border-radius: 999px; padding: 6px 14px; cursor: pointer; }}
[data-fragment] {{ opacity: 0; transition: opacity 0.35s ease, transform 0.35s ease; }}
[data-fragment].is-fragment-visible {{ opacity: 1; }}
@media print {{
  .presenta-controls {{ display: none; }}
  .presenta-slide {{ display: block !important; page-break-after: always; }}
  [data-fragment] {{ opacity: 1 !important; }}
}}
{slide_styles()}
"""


def theme_css(manifest: dict[str, Any]) -> str:
    return _theme_css(manifest) + slide_styles()


def build_standalone_html(deck: Deck, manifest: dict[str, Any], images: dict[str, str] | None = None) -> str:
    images = images or {}
    slides_html = []
    for slide in deck.slides:
        slides_html.append(
            f'<section class="presenta-slide" data-slide-id="{html.escape(slide.id)}">'
            f"{render_slide_html(slide, images=images)}</section>"
        )
    payload = json.dumps(deck.model_dump(mode="json", by_alias=True), ensure_ascii=False).replace(
        "</", "<\\/"
    )
    title = html.escape(deck.meta.title)
    theme_name = html.escape(str(manifest.get("name") or deck.theme_id))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'" />
<title>{title} · Presenta</title>
<style>{_theme_css(manifest)}</style>
</head>
<body>
<div class="presenta-viewer">
{"".join(slides_html)}
</div>
<div class="presenta-controls">
  <button class="presenta-prev" type="button">上一页</button>
  <span id="presenta-progress">1 / {max(1, len(deck.slides))}</span>
  <button class="presenta-next" type="button">下一页</button>
  <span>· {theme_name} · ← → 翻页 · F 全屏</span>
</div>
<script id="presenta-deck" type="application/json">{payload}</script>
<script>{_STANDALONE_SCRIPT}</script>
</body>
</html>"""
