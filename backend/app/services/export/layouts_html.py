import html
import re
from typing import Any

from app.api.schemas.deck import Element, ImageMedia, Slide

_PALETTE = ["#7A1F1F", "#1F4E79", "#6b6a5f", "#3f6b55", "#9a6a2f", "#5d5f7a"]


def esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


_CJK_RUN = re.compile(r"([\u3400-\u9fff\u3000-\u303f]+)")
_RICH_TOKEN = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|\^[^^]+\^)")


def _cjk_html(raw: str) -> str:
    parts = [part for part in _CJK_RUN.split(raw) if part]
    rendered: list[str] = []
    for index, part in enumerate(parts):
        is_cjk = bool(re.search(r"[\u3400-\u9fff]", part))
        previous = parts[index - 1] if index > 0 else ""
        following = parts[index + 1] if index + 1 < len(parts) else ""
        needs_gap = (
            not is_cjk
            and bool(re.search(r"[A-Za-z0-9]", part))
            and (
                bool(re.search(r"[\u3400-\u9fff]", previous))
                or bool(re.search(r"[\u3400-\u9fff]", following))
            )
        )
        escaped = esc(part)
        gap = "\u200b" if needs_gap else ""
        rendered.append(
            f'<span class="cjk-compensate">{escaped}</span>'
            if is_cjk
            else f"{gap}{escaped}{gap}"
        )
    return "".join(rendered)


def text_html(value: Any) -> str:
    raw = str(value) if value is not None else ""
    rendered: list[str] = []
    for token in _RICH_TOKEN.split(raw):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            rendered.append(f"<strong>{_cjk_html(token[2:-2])}</strong>")
        elif token.startswith("`") and token.endswith("`"):
            rendered.append(f"<code>{_cjk_html(token[1:-1])}</code>")
        elif token.startswith("*") and token.endswith("*"):
            rendered.append(f"<em>{_cjk_html(token[1:-1])}</em>")
        elif token.startswith("^") and token.endswith("^"):
            rendered.append(f"<sup>{_cjk_html(token[1:-1])}</sup>")
        else:
            rendered.append(_cjk_html(token))
    return "".join(rendered)


def _media(media: dict[str, Any], images: dict[str, str]) -> str:
    kind = (media or {}).get("kind")
    if kind == "image":
        try:
            parsed = ImageMedia.model_validate(media)
        except Exception:
            return '<figure class="media-placeholder">图片资产缺失</figure>'
        source = images.get(parsed.asset_id)
        if not source:
            return '<figure class="media-placeholder">图片资产未内联</figure>'
        return (
            f'<figure class="media-frame"><img src="{source}" alt="{esc(parsed.alt)}" '
            f'style="object-fit:{parsed.fit}" /></figure>'
        )
    if kind == "chart":
        return f'<figure class="media-frame">{chart_svg(media)}</figure>'
    if kind == "table":
        columns = media.get("columns") or []
        rows = (media.get("rows") or [])[:10]
        head = "".join(f"<th>{esc(column)}</th>" for column in columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
        )
        return f'<figure class="media-frame"><table class="slot-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></figure>'
    return '<figure class="media-placeholder">媒体占位</figure>'


def chart_svg(chart: dict[str, Any]) -> str:
    series: list[dict[str, Any]] = []
    for series_entry in chart.get("series") or []:
        entry = series_entry if isinstance(series_entry, dict) else {}
        points: list[dict[str, Any]] = [
            {"label": str(point.get("label", "")), "value": float(point.get("value") or 0)}
            for point in entry.get("points") or []
            if isinstance(point, dict)
        ]
        series.append({"name": str(entry.get("name", "")), "points": points})
    width, height = 760, 360
    pad = {"left": 54, "right": 28, "top": 26, "bottom": 46}
    values = [point["value"] for entry in series for point in entry["points"]] or [0]
    maximum = max([1.0, *values])
    minimum = min([0.0, *values])
    span = (maximum - minimum) or 1
    plot_w = width - pad["left"] - pad["right"]
    plot_h = height - pad["top"] - pad["bottom"]
    labels = series[0]["points"] if series else []
    chart_type = str(chart.get("type") or "bar")

    def y_of(value: float) -> float:
        return pad["top"] + plot_h - ((value - minimum) / span) * plot_h

    def x_of(index: int) -> float:
        if len(labels) <= 1:
            return pad["left"] + plot_w / 2
        return pad["left"] + (index / (len(labels) - 1)) * plot_w

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img">']
    if chart_type == "pie":
        total = sum(point["value"] for point in (series[0]["points"] if series else [])) or 1
        import math

        angle = -math.pi / 2
        cx, cy, radius = width / 2, height / 2, min(plot_w, plot_h) / 2.2
        for index, point in enumerate(series[0]["points"] if series else []):
            sweep = (point["value"] / total) * math.pi * 2
            sx, sy = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            angle += sweep
            ex, ey = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            large = 1 if sweep > math.pi else 0
            parts.append(
                f'<path d="M {cx} {cy} L {sx:.2f} {sy:.2f} A {radius} {radius} 0 {large} 1 {ex:.2f} {ey:.2f} Z" '
                f'fill="{_PALETTE[index % len(_PALETTE)]}" stroke="#ffffff" stroke-width="2" />'
            )
        parts.append("</svg>")
        return "".join(parts)

    for ratio in (0, 0.25, 0.5, 0.75, 1):
        y = pad["top"] + plot_h * ratio
        parts.append(
            f'<line x1="{pad["left"]}" x2="{width - pad["right"]}" y1="{y:.1f}" y2="{y:.1f}" '
            'stroke="rgba(0,0,0,0.12)" stroke-dasharray="3 5" />'
        )

    for series_index, entry in enumerate(series):
        color = _PALETTE[series_index % len(_PALETTE)]
        if chart_type == "bar":
            group_width = plot_w / max(1, len(entry["points"]))
            bar_width = max(8, (group_width * 0.6) / max(1, len(series)))
            for index, point in enumerate(entry["points"]):
                x = pad["left"] + index * group_width + group_width * 0.2 + series_index * bar_width
                y = y_of(point["value"])
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                    f'height="{pad["top"] + plot_h - y:.1f}" fill="{color}" rx="3" />'
                )
            continue
        if chart_type == "scatter":
            for index, point in enumerate(entry["points"]):
                parts.append(
                    f'<circle cx="{x_of(index):.1f}" cy="{y_of(point["value"]):.1f}" r="6" fill="{color}" />'
                )
            continue
        path = " ".join(
            f'{"M" if index == 0 else "L"} {x_of(index):.1f} {y_of(point["value"]):.1f}'
            for index, point in enumerate(entry["points"])
        )
        if chart_type == "area" and entry["points"]:
            parts.append(
                f'<path d="{path} L {x_of(len(entry["points"]) - 1):.1f} {pad["top"] + plot_h:.1f} '
                f'L {x_of(0):.1f} {pad["top"] + plot_h:.1f} Z" fill="{color}" opacity="0.18" />'
            )
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3" />')
        for index, point in enumerate(entry["points"]):
            parts.append(
                f'<circle cx="{x_of(index):.1f}" cy="{y_of(point["value"]):.1f}" r="4" fill="{color}" />'
            )

    for index, point in enumerate(labels):
        parts.append(
            f'<text x="{x_of(index):.1f}" y="{height - 14}" text-anchor="middle" font-size="13" fill="#55565c">{esc(point["label"])}</text>'
        )
    unit = esc(chart.get("unit") or "")
    for value in (minimum, (minimum + maximum) / 2, maximum):
        parts.append(
            f'<text x="{pad["left"] - 10}" y="{y_of(value) + 4:.1f}" text-anchor="end" font-size="12" fill="#55565c">'
            f"{round(value, 2)}{unit}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _render_layout_html(slide: Slide, images: dict[str, str] | None = None) -> str:
    images = images or {}
    slots = slide.slots
    layout = slide.layout
    degraded = '<span class="degraded-flag">degraded</span>' if slide.degraded else ""
    source_note = ""
    if slide.provenance:
        quotes = "；".join(entry.quote[:80] for entry in slide.provenance[:2])
        source_note = f'<div class="export-source">来源：{esc(quotes)}</div>'

    if layout == "cover":
        background: dict[str, Any] = (
            slots["bg"] if isinstance(slots.get("bg"), dict) else {}
        )
        bg_html = ""
        if background.get("kind") == "image" and background.get("assetId") in images:
            bg_html = f'<img class="cover-bg" src="{images[background["assetId"]]}" alt="" />'
        inner = (
            f'<div class="cover-inner">'
            f'<span class="kicker">{text_html(slots.get("kicker", ""))}</span>'
            f'<h1 class="cover-title">{text_html(slots.get("title", ""))}</h1>'
            f'<p class="cover-subtitle">{text_html(slots.get("subtitle", ""))}</p>'
            "</div>"
        )
        return f'<div class="layout cover">{bg_html}{inner}<div class="cover-rule"></div>{degraded}</div>'

    if layout == "toc":
        toc_items = "".join(
            f'<li><span class="toc-index">{index + 1:02d}</span><span>{text_html(item)}</span></li>'
            for index, item in enumerate(_list(slots.get("items")))
        )
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<ol class="toc-list">{toc_items}</ol>{degraded}</div>'
        )

    if layout == "bullets":
        bullet_items: list[str] = []
        for item in _list(slots.get("items")):
            if isinstance(item, dict):
                main, sub = _text(item.get("text")), _text(item.get("sub"))
            else:
                main, sub = _text(item), ""
            sub_html = f'<span class="bullet-sub">{text_html(sub)}</span>' if sub else ""
            bullet_items.append(
                '<li data-fragment><span class="bullet-mark"></span>'
                f'<span class="bullet-body"><span class="bullet-main">{text_html(main)}</span>{sub_html}</span></li>'
            )
        lead = f'<p class="lead">{text_html(slots.get("lead", ""))}</p>' if slots.get("lead") else ""
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'{lead}<div class="bullets"><ul>{"".join(bullet_items)}</ul></div>{degraded}</div>'
        )

    if layout in {"split-lr", "split-tb"}:
        media_html = _media(slots.get("media") or {}, images)
        container = "split-lr" if layout == "split-lr" else "split-tb"
        side = " media-left" if layout == "split-lr" and slots.get("mediaSide") == "left" else ""
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="{container}{side}"><div class="body-text">{text_html(slots.get("body", ""))}</div>'
            f"{media_html}</div>{degraded}{source_note}</div>"
        )

    if layout == "cards-3":
        cards = "".join(
            f'<div class="card"><span class="card-index">{index + 1:02d}</span>'
            f'<h3>{text_html((card or {}).get("heading", ""))}</h3>'
            f'<p>{text_html((card or {}).get("text", ""))}</p></div>'
            for index, card in enumerate(_list(slots.get("cards")))
            if isinstance(card, dict)
        )
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="cards">{cards}</div>{degraded}</div>'
        )

    if layout == "chart":
        return (
            f'<div class="layout padded"><h2 class="section-title">{esc(slots.get("title", ""))}</h2>'
            f'<div class="chart-wrap">{chart_svg(slots.get("chart") or {})}'
            f'<div class="chart-caption"><span>{esc(slots.get("caption", ""))}</span>'
            f'<span class="source-line">{text_html(slots.get("source", ""))}</span></div></div>'
            f"{degraded}</div>"
        )

    if layout == "big-number":
        numbers = "".join(
            f'<div class="number-block"><span class="number-value">{text_html((entry or {}).get("value", ""))}</span>'
            f'<span class="number-label">{text_html((entry or {}).get("label", ""))}</span></div>'
            for entry in _list(slots.get("numbers"))
            if isinstance(entry, dict)
        )
        note = f'<p class="note-line">{text_html(slots.get("note", ""))}</p>' if slots.get("note") else ""
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="numbers">{numbers}</div>{note}{degraded}{source_note}</div>'
        )

    if layout == "quote":
        return (
            f'<div class="layout quote-layout"><span class="quote-mark">“</span>'
            f'<blockquote class="quote-text">{text_html(slots.get("quote", ""))}</blockquote>'
            f'<div class="quote-meta"><span>{text_html(slots.get("author", ""))}</span>'
            f'<span class="source-line">{text_html(slots.get("source", ""))}</span></div>{degraded}</div>'
        )

    if layout == "compare":
        columns = []
        for side, tag in (("left", "A"), ("right", "B")):
            items = "".join(f"<li>{text_html(item)}</li>" for item in _list(slots.get(side)))
            columns.append(
                f'<div class="compare-col {side}"><span class="compare-tag">{tag}</span>'
                f"<ul>{items}</ul></div>"
            )
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="compare">{"".join(columns)}</div>{degraded}</div>'
        )

    if layout == "timeline":
        nodes = "".join(
            f'<div class="timeline-node"><span class="timeline-time">{text_html((node or {}).get("time", ""))}</span>'
            f'<span class="timeline-dot"></span>'
            f'<span class="timeline-text">{text_html((node or {}).get("text", ""))}</span></div>'
            for node in _list(slots.get("nodes"))
            if isinstance(node, dict)
        )
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="timeline">{nodes}</div>{degraded}</div>'
        )

    if layout == "process":
        steps = "".join(
            f'<div class="process-step"><span class="process-index">{index + 1}</span>'
            f'<h3>{text_html((step or {}).get("label", ""))}</h3>'
            f'<p>{text_html((step or {}).get("text", ""))}</p></div>'
            for index, step in enumerate(_list(slots.get("steps")))
            if isinstance(step, dict)
        )
        return (
            f'<div class="layout padded"><h2 class="section-title">{text_html(slots.get("title", ""))}</h2>'
            f'<div class="process">{steps}</div>{degraded}</div>'
        )

    if layout == "full-image":
        return (
            f'<div class="layout full-image"><div class="full-image-media">'
            f'{_media(slots.get("media") or {}, images)}</div>'
            f'<div class="full-image-meta"><span>{text_html(slots.get("caption", ""))}</span>'
            f'<span class="source-line">{text_html(slots.get("source", ""))}</span></div>{degraded}</div>'
        )

    if layout == "ending":
        return (
            f'<div class="layout ending"><h2 class="ending-title">{text_html(slots.get("title", ""))}</h2>'
            f'<p class="ending-message">{text_html(slots.get("message", ""))}</p>'
            f'<span class="ending-contact">{text_html(slots.get("contact", ""))}</span>{degraded}</div>'
        )

    return (
        f'<div class="layout padded"><h2 class="section-title">{esc(slots.get("title", "未命名页面"))}</h2>'
        f"{degraded}</div>"
    )


def _camel_to_kebab(name: str) -> str:
    out: list[str] = []
    for ch in name:
        if ch.isupper():
            out.append("-")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _style_string(override: dict[str, str | int | float]) -> str:
    return ";".join(
        f"{_camel_to_kebab(k)}:{esc(v)}" for k, v in override.items()
    )


def _slot_style_rules(elements: list[Element], slide_id: str) -> str:
    rules: list[str] = []
    for element in elements:
        if not element.style_override and element.layout is None:
            continue
        declarations: list[str] = []
        if element.layout is not None:
            layout = element.layout
            declarations.append(
                f"position:absolute;left:{(layout.x / 12) * 100:.4f}%;"
                f"top:{layout.y:.4f}%;width:{(layout.w / 12) * 100:.4f}%;"
                f"height:{layout.h:.4f}%"
            )
        if element.style_override:
            declarations.append(_style_string(element.style_override))
        rules.append(
            f'.slide-root[data-slide-id="{esc(slide_id)}"] '
            f'[data-slot="{esc(element.slot_path)}"] {{ {";".join(declarations)} }}'
        )
    return "\n".join(rules)


def _element_asset_id(slide: Slide, element: Element) -> str | None:
    slot_value = slide.slots.get(element.slot_path)
    if isinstance(slot_value, dict) and slot_value.get("kind") == "image":
        asset_id = slot_value.get("assetId")
        if isinstance(asset_id, str) and asset_id:
            return asset_id
    return None


def _render_elements(slide: Slide, elements: list[Element], images: dict[str, str]) -> str:
    parts: list[str] = []
    for element in elements:
        if element.layout is None:
            continue
        layout = element.layout
        left = (layout.x / 12.0) * 100.0
        width = (layout.w / 12.0) * 100.0
        style = (
            f"position:absolute;left:{left:.4f}%;top:{layout.y:.4f}%;"
            f"width:{width:.4f}%;height:{layout.h:.4f}%"
        )
        if element.style_override:
            style += ";" + _style_string(element.style_override)
        if element.type == "image":
            asset_id = _element_asset_id(slide, element)
            slot = images.get(asset_id) if asset_id else None
            inner = (
                f'<img src="{esc(slot)}" alt="" style="width:100%;height:100%;object-fit:cover" />'
                if slot
                else '<span class="media-placeholder">图片未内联</span>'
            )
        elif element.type == "text":
            slot_value = slide.slots.get(element.slot_path)
            inner = f'<span class="element-text">{text_html(slot_value)}</span>'
        elif element.type == "chart":
            chart = slide.slots.get(element.slot_path)
            inner = chart_svg(chart) if isinstance(chart, dict) else ""
        elif element.type == "table":
            table = slide.slots.get(element.slot_path)
            inner = _media(table, images) if isinstance(table, dict) else ""
        else:
            inner = f'<span class="element-{esc(element.type)}"></span>'
        parts.append(
            f'<div class="element element-{esc(element.type)}" data-element-id="{esc(element.id)}" '
            f'style="{style}">{inner}</div>'
        )
    return "".join(parts)


def render_slide_html(slide: Slide, images: dict[str, str] | None = None) -> str:
    images = images or {}
    base = _render_layout_html(slide, images=images)
    slot_rules = _slot_style_rules(slide.elements, slide.id)
    free_elements = [
        element
        for element in slide.elements
        if element.layout is not None and element.slot_path not in slide.slots
    ]
    elements_html = _render_elements(slide, free_elements, images)
    overlay = f'<div class="element-layer">{elements_html}</div>' if elements_html else ""
    style_tag = f"<style>{slot_rules}</style>" if slot_rules else ""
    return (
        f'<div class="slide-root" data-slide-id="{esc(slide.id)}">'
        f"{style_tag}{base}{overlay}</div>"
    )


def slide_styles() -> str:
    return """
.slide-root { width: 100%; height: 100%; position: relative; overflow: hidden; }
.layout { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; position: relative; }
.element-layer { position: absolute; inset: 0; pointer-events: none; }
.element { pointer-events: auto; box-sizing: border-box; }
.element-text { display: block; width: 100%; height: 100%; overflow: hidden; }
:root { --cjk-scale: 1.03; --line-height-cjk: 1.75; --line-height-mixed: 1.65; --line-height-heading: 1.25; }
body { text-autospace: normal; line-break: strict; word-break: normal; overflow-wrap: anywhere; }
.cjk-compensate { font-size: calc(1em * var(--cjk-scale)); }
.zh-heavy { line-height: var(--line-height-cjk); }
.mixed { line-height: var(--line-height-mixed); }
.padded { padding: 64px 84px 56px; gap: 18px; }
.section-title { font-family: var(--font-display, serif); font-size: 46px; line-height: var(--line-height-heading); margin: 0 0 6px; }
.lead { font-size: 20px; color: var(--color-muted); margin: 0 0 6px; }
.kicker { display: inline-block; font-size: 15px; letter-spacing: .22em; text-transform: uppercase; color: var(--color-primary); }
.cover { justify-content: flex-end; padding: 0 0 84px 96px; position: relative; }
.cover-inner { position: relative; z-index: 2; display: flex; flex-direction: column; gap: 16px; max-width: 820px; }
.cover-title { font-family: var(--font-display, serif); font-size: 76px; line-height: 1.06; margin: 0; letter-spacing: -0.02em; }
.cover-subtitle { font-size: 24px; color: var(--color-muted); margin: 0; max-width: 34ch; }
.cover-rule { position: absolute; left: 96px; bottom: 56px; width: 132px; height: 5px; background: var(--color-primary); }
.cover-bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.toc-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 14px 40px; }
.toc-list li { display: flex; gap: 16px; align-items: baseline; font-size: 24px; border-bottom: 1px solid rgba(0,0,0,0.12); padding-bottom: 12px; }
.toc-index { color: var(--color-primary); font-size: 14px; }
.bullets { flex: 1; }
.bullets ul { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 16px; }
.bullets li { display: flex; gap: 16px; font-size: 22px; line-height: 1.5; }
.bullet-mark { width: 8px; height: 8px; border-radius: 50%; background: var(--color-primary); margin-top: 11px; flex: none; }
.bullet-body { display: flex; flex-direction: column; gap: 4px; }
.bullet-sub { font-size: 16px; color: var(--color-muted); }
.split-lr { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; flex: 1; min-height: 0; align-items: center; }
.split-lr.media-left .body-text { order: 2; }
.split-tb { display: grid; grid-template-rows: auto 1fr; gap: 22px; flex: 1; min-height: 0; }
.body-text { font-size: 21px; line-height: var(--line-height-mixed); }
.media-frame { margin: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 10px; min-height: 0; height: 100%; }
.media-frame img { width: 100%; height: 100%; border-radius: 10px; }
.media-placeholder { display: grid; place-items: center; border: 1px dashed rgba(0,0,0,0.25); color: #6b6c73; border-radius: 10px; height: 100%; margin: 0; }
.chart-svg { width: 100%; height: auto; max-height: 420px; }
.slot-table { width: 100%; border-collapse: collapse; font-size: 16px; }
.slot-table th { text-align: left; border-bottom: 2px solid var(--color-primary); padding: 8px 10px; }
.slot-table td { border-bottom: 1px solid rgba(0,0,0,0.1); padding: 8px 10px; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; flex: 1; }
.card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md, 8px); padding: 26px; display: flex; flex-direction: column; gap: 10px; }
.card-index { color: var(--color-primary); font-size: 13px; }
.card h3 { font-family: var(--font-display, serif); font-size: 24px; margin: 0; }
.card p { margin: 0; font-size: 16px; line-height: 1.62; color: var(--color-muted); }
.chart-wrap { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 10px; }
.chart-caption { display: flex; justify-content: space-between; gap: 16px; font-size: 15px; color: var(--color-muted); }
.source-line { font-size: 13px; color: var(--color-muted); }
.numbers { display: flex; gap: 54px; flex-wrap: wrap; margin-top: 26px; }
.number-block { display: flex; flex-direction: column; gap: 6px; }
.number-value { font-family: var(--font-display, serif); font-size: 96px; line-height: 1; color: var(--color-primary); }
.number-label { font-size: 19px; color: var(--color-muted); }
.note-line { margin-top: auto; font-size: 14px; color: var(--color-muted); }
.quote-layout { justify-content: center; padding: 90px 110px; gap: 20px; }
.quote-mark { font-family: var(--font-display, serif); font-size: 140px; line-height: .6; color: var(--color-primary); }
.quote-text { margin: 0; font-family: var(--font-display, serif); font-size: 40px; line-height: 1.42; }
.quote-meta { display: flex; gap: 18px; align-items: baseline; font-size: 16px; color: var(--color-muted); }
.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; flex: 1; }
.compare-col { border: 1px solid var(--color-border); border-radius: var(--radius-md, 8px); padding: 24px; background: var(--color-surface); }
.compare-col.right { background: #f2efe8; }
.compare-tag { font-size: 12px; letter-spacing: .2em; color: var(--color-primary); }
.compare-col ul { margin: 12px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; font-size: 18px; }
.timeline { display: flex; gap: 18px; margin-top: 34px; flex: 1; align-items: flex-start; }
.timeline-node { flex: 1; display: flex; flex-direction: column; gap: 10px; }
.timeline-time { color: var(--color-primary); font-size: 14px; }
.timeline-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--color-primary); }
.timeline-text { font-size: 17px; line-height: 1.55; padding-top: 8px; border-top: 1px solid var(--color-border); }
.process { display: flex; gap: 16px; margin-top: 26px; flex: 1; }
.process-step { flex: 1; border-top: 3px solid var(--color-primary); padding-top: 18px; display: flex; flex-direction: column; gap: 8px; }
.process-index { font-family: var(--font-display, serif); font-size: 34px; color: var(--color-primary); }
.process-step h3 { font-size: 21px; margin: 0; }
.process-step p { margin: 0; font-size: 15px; color: var(--color-muted); line-height: 1.6; }
.full-image { position: relative; }
.full-image-media { position: absolute; inset: 0; }
.full-image-media .media-frame { border-radius: 0; height: 100%; }
.full-image-meta { position: absolute; left: 64px; right: 64px; bottom: 36px; display: flex; justify-content: space-between; gap: 16px; color: #fff; background: rgba(10,10,14,0.55); padding: 10px 16px; border-radius: 8px; font-size: 14px; }
.ending { align-items: center; justify-content: center; gap: 18px; text-align: center; padding: 80px; }
.ending-title { font-family: var(--font-display, serif); font-size: 74px; margin: 0; }
.ending-message { font-size: 24px; color: var(--color-muted); margin: 0; max-width: 40ch; }
.ending-contact { font-size: 14px; letter-spacing: .18em; color: var(--color-primary); }
.degraded-flag { position: absolute; right: 18px; top: 16px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: #b23; border: 1px solid #b23; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,.6); }
.export-source { position: absolute; left: 84px; bottom: 18px; font-size: 11px; color: rgba(0,0,0,.5); }
"""
