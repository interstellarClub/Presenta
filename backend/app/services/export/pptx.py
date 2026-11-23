import io
from typing import Any

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.api.schemas.deck import Deck, Slide

_TRANSITION_MAP = {
    "fade": "fade",
    "push": "push",
    "wipe": "wipe",
    "cover": "cover",
    "zoom": "zoom",
}

_SLIDE_W = Inches(13.333)
_SLIDE_H = Inches(7.5)


def _hex(color: str | None, fallback: str = "1B1B1F") -> RGBColor:
    value = (color or fallback).lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        value = fallback.lstrip("#")
    return RGBColor.from_string(value.upper())


def _inject_transition(slide, effect: str, duration_ms: int) -> None:
    mapped = _TRANSITION_MAP.get(effect)
    if mapped is None:
        return
    element = slide._element
    for existing in element.findall(qn("p:transition")):
        element.remove(existing)
    transition = etree.SubElement(element, qn("p:transition"))
    transition.set("spd", "med")
    child = etree.SubElement(transition, qn(f"p:{mapped}"))
    child.set("dur", str(max(0, int(duration_ms))))

    timing = element.find(qn("p:timing"))
    if timing is not None:
        element.remove(transition)
        timing.addprevious(transition)


def _add_textbox(slide, left, top, width, height, text: str, *, size: int, color: str, bold=False):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = _hex(color)
    return box


def _slide_body_lines(slide: Slide) -> tuple[str, list[str]]:
    slots = slide.slots
    title = str(slots.get("title") or slots.get("quote") or "未命名页面")
    lines: list[str] = []
    for key in ("subtitle", "lead", "body", "caption", "source", "message", "contact", "note"):
        value = slots.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(value.strip())
    for key in ("items", "left", "right", "cards", "steps", "nodes", "numbers"):
        for entry in slots.get(key) or []:
            if isinstance(entry, str):
                lines.append(entry)
            elif isinstance(entry, dict):
                parts = [str(entry.get(field)) for field in ("heading", "text", "label", "time", "value") if entry.get(field)]
                if parts:
                    lines.append(" · ".join(parts))
    chart = slots.get("chart")
    if isinstance(chart, dict):
        for series in chart.get("series") or []:
            points = series.get("points") or []
            rendered = "，".join(f"{point.get('label')}={point.get('value')}" for point in points[:8])
            if rendered:
                lines.append(f"{series.get('name', '数据')}：{rendered}")
    return title, lines[:8]


def build_pptx(
    *,
    deck: Deck,
    manifest: dict[str, Any],
    images: dict[str, str],
    slides_html: list[str],
    options: dict[str, Any],
) -> tuple[bytes, list[str]]:
    tokens = (manifest.get("tokens") or {}).get("color") or {}
    text_color = tokens.get("text", "#1B1B1F")
    primary = tokens.get("primary", "#7A1F1F")
    muted = tokens.get("muted", "#5B5B66")

    presentation = Presentation()
    presentation.slide_width = _SLIDE_W
    presentation.slide_height = _SLIDE_H

    notes: list[str] = [
        "元素动效以静态关键帧/图片承载，换页转场仅使用白名单原生效果",
        "图表以图片或文本快照插入，PPT 内不可编辑；改数据请回平台",
    ]
    blank_layout = presentation.slide_layouts[6]
    for index, slide in enumerate(deck.slides):
        page = presentation.slides.add_slide(blank_layout)
        title, lines = _slide_body_lines(slide)
        _add_textbox(page, Inches(0.7), Inches(0.5), Inches(11.9), Inches(1.2), title, size=32, color=text_color, bold=True)
        body = "\n".join(f"• {line}" for line in lines) or "（本页为降级或空内容页）"
        _add_textbox(page, Inches(0.9), Inches(1.9), Inches(11.5), Inches(4.6), body, size=18, color=muted)
        _add_textbox(
            page,
            Inches(0.7),
            Inches(6.7),
            Inches(11.9),
            Inches(0.4),
            f"Presenta · {deck.meta.title} · 第 {index + 1} 页",
            size=10,
            color=primary,
        )

        provenance_lines = [
            f"[{entry.type}] {entry.quote[:160]} (P{entry.source_ref.line_start})"
            for entry in slide.provenance
        ]
        if slide.degraded:
            provenance_lines.append(f"降级页：{slide.degraded_reason or '未通过 Schema 校验'}")
        if slide.notes:
            provenance_lines.append(f"备注：{slide.notes}")
        page.notes_slide.notes_text_frame.text = "\n".join(provenance_lines) or "无来源备注"

        if slide.transition:
            _inject_transition(page, slide.transition.effect, slide.transition.duration)

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue(), notes