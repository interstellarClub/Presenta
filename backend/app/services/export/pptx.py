import base64
import binascii
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


def _decode_data_uri(uri: str) -> bytes | None:
    if not uri.startswith("data:"):
        return None
    try:
        _, b64 = uri.split(",", 1)
        return base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None


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


def _add_image(slide, images: dict[str, str], asset_id: str | None, left, top, width, height) -> bool:
    if not asset_id:
        return False
    uri = images.get(asset_id)
    if not uri:
        return False
    blob = _decode_data_uri(uri)
    if blob is None:
        return False
    try:
        slide.shapes.add_picture(io.BytesIO(blob), left, top, width, height)
        return True
    except Exception:
        return False


def _add_table(slide, columns: list[str], rows: list[list[str]], left, top, width, height) -> bool:
    if not columns or not rows:
        return False
    try:
        table_shape = slide.shapes.add_table(len(rows) + 1, len(columns), left, top, width, height)
        table = table_shape.table
        for col_index, header in enumerate(columns):
            cell = table.cell(0, col_index)
            cell.text = str(header)
        for row_index, row in enumerate(rows[:18], start=1):
            for col_index, value in enumerate(row[: len(columns)]):
                cell = table.cell(row_index, col_index)
                cell.text = str(value)
        return True
    except Exception:
        return False


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


def _media_asset_id(media: Any) -> str | None:
    if isinstance(media, dict) and media.get("kind") == "image":
        asset_id = media.get("assetId")
        if isinstance(asset_id, str) and asset_id:
            return asset_id
    return None


def _media_table(media: Any) -> tuple[list[str], list[list[str]]] | None:
    if isinstance(media, dict) and media.get("kind") == "table":
        columns = [str(c) for c in (media.get("columns") or [])]
        rows = [[str(cell) for cell in row] for row in (media.get("rows") or [])]
        if columns and rows:
            return columns, rows
    return None


def _slide_media_targets(slide: Slide) -> list[tuple[str, Any]]:
    slots = slide.slots
    targets: list[tuple[str, Any]] = []
    layout = slide.layout
    if layout == "cover":
        bg = slots.get("bg")
        if isinstance(bg, dict):
            targets.append(("image", bg))
    elif layout in {"split-lr", "split-tb", "full-image"}:
        targets.append(("media", slots.get("media") or {}))
    elif layout == "chart":
        targets.append(("chart", slots.get("chart") or {}))
    return targets


def build_pptx(
    *,
    deck: Deck,
    manifest: dict[str, Any],
    images: dict[str, str],
    slides_html: list[str],
    options: dict[str, Any],
    rendered_pages: dict[int, bytes] | None = None,
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
        rendered = (rendered_pages or {}).get(index)
        if rendered is not None:
            page.shapes.add_picture(
                io.BytesIO(rendered), 0, 0, width=_SLIDE_W, height=_SLIDE_H
            )
            notes.append(f"第 {index + 1} 页使用服务端渲染快照以保持视觉一致")
        else:
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

        media_inserted = False
        for slot_name, media in _slide_media_targets(slide) if rendered is None else []:
            if slot_name == "image":
                asset_id = _media_asset_id(media)
                if _add_image(page, images, asset_id, Inches(7.2), Inches(1.9), Inches(5.4), Inches(4.4)):
                    media_inserted = True
            elif slot_name == "media":
                asset_id = _media_asset_id(media)
                if asset_id and _add_image(page, images, asset_id, Inches(7.2), Inches(1.9), Inches(5.4), Inches(4.4)):
                    media_inserted = True
                table_data = _media_table(media)
                if table_data and _add_table(page, table_data[0], table_data[1], Inches(7.2), Inches(1.9), Inches(5.4), Inches(4.4)):
                    media_inserted = True
            elif slot_name == "chart":
                chart_text = _slide_body_lines(slide)[1]
                if chart_text:
                    media_inserted = True
        if media_inserted:
            notes.append(f"第 {index + 1} 页已插入媒体内容")

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
