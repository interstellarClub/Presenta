import mimetypes
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.ingest.omml import convert_paragraph_math, table_to_csv

_HEADING_STYLES = {
    "Title": 1,
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "Heading 4": 4,
    "Heading 5": 5,
    "Heading 6": 6,
    "Subtitle": 2,
}
_MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_IMAGE_SUFFIX = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "image/x-emf": "emf",
    "image/x-wmf": "wmf",
}


@dataclass
class ExtractedImage:
    asset_id: str
    blob: bytes
    mime: str
    name: str
    source_ref: dict[str, Any]


@dataclass
class ExtractedTable:
    asset_id: str
    columns: list[str]
    rows: list[list[str]]
    source_ref: dict[str, Any]
    csv_text: str = ""


@dataclass
class ExtractedFormula:
    asset_id: str
    latex: str | None
    original_xml: str
    source_ref: dict[str, Any]


@dataclass
class DocxResult:
    markdown: str
    images: list[ExtractedImage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    formulas: list[ExtractedFormula] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)


def _new_asset_id() -> str:
    return uuid.uuid4().hex


def _iter_body(document: DocxDocument) -> list[Paragraph | Table]:
    body = document.element.body
    items: list[Paragraph | Table] = []
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            items.append(Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            items.append(Table(child, document))
    return items


def _style_heading_level(paragraph: Paragraph) -> int | None:
    try:
        name = paragraph.style.name if paragraph.style is not None else ""
    except (KeyError, AttributeError):
        return None
    return _HEADING_STYLES.get(name or "")


def _is_list(paragraph: Paragraph) -> tuple[bool, int]:
    try:
        name = paragraph.style.name if paragraph.style is not None else ""
    except (KeyError, AttributeError):
        name = ""
    numbered = paragraph._p.find(qn("w:pPr")) is not None and paragraph._p.find(qn("w:pPr")).find(
        qn("w:numPr")
    ) is not None
    if (name or "").lower().startswith(("list", "bullet")) or numbered:
        level = 0
        ppr = paragraph._p.find(qn("w:pPr"))
        if ppr is not None:
            num_pr = ppr.find(qn("w:numPr"))
            if num_pr is not None:
                ilvl = num_pr.find(qn("w:ilvl"))
                if ilvl is not None:
                    try:
                        level = int(ilvl.get(qn("w:val")) or 0)
                    except (TypeError, ValueError):
                        level = 0
        return True, min(level, 3)
    return False, 0


def _run_text(run: Any) -> str:
    text = run.text or ""
    if not text:
        return ""
    if run.font.superscript:
        text = f"^{text}^"
    if run.bold:
        text = f"**{text}**"
    if run.italic:
        text = f"*{text}*"
    return text


def _paragraph_images(paragraph: Paragraph, document: DocxDocument, line_no: int) -> list[ExtractedImage]:
    images: list[ExtractedImage] = []
    for blip in paragraph._p.findall(".//" + qn("a:blip")):
        rel_id = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not rel_id:
            continue
        part = document.part.related_parts.get(rel_id)
        if part is None:
            continue
        blob = getattr(part, "blob", b"")
        if not blob:
            continue
        mime = getattr(part, "content_type", None) or mimetypes.guess_type(
            getattr(part, "partname", "")
        )[0] or "image/png"
        images.append(
            ExtractedImage(
                asset_id=_new_asset_id(),
                blob=blob,
                mime=mime,
                name=str(getattr(part, "partname", "image")),
                source_ref={
                    "lineStart": line_no,
                    "colStart": 0,
                    "lineEnd": line_no,
                    "colEnd": 0,
                },
            )
        )
    return images


def _has_math(paragraph: Paragraph) -> bool:
    return any(element.tag == f"{{{_MATH_NS}}}oMath" for element in paragraph._p.iter())


def _table_payload(table: Table) -> tuple[list[str], list[list[str]]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        rows.append([colspan for colspan in cells])
    if not rows:
        return [], []
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    columns = normalized[0]
    if not any(columns):
        columns = [f"列{i + 1}" for i in range(width)]
    return columns, normalized[1:]


def docx_to_markdown(path: Path) -> DocxResult:
    from lxml import etree

    document: DocxDocument = Document(str(path))
    result = DocxResult(markdown="")
    lines: list[str] = []

    def emit(text: str) -> int:
        lines.append(text)
        return len(lines)

    for item in _iter_body(document):
        if isinstance(item, Table):
            columns, rows = _table_payload(item)
            if not columns:
                continue
            line_start = len(lines) + 1
            if lines and lines[-1] != "":
                emit("")
            header = "| " + " | ".join(columns) + " |"
            divider = "| " + " | ".join("---" for _ in columns) + " |"
            emit(header)
            emit(divider)
            for row in rows:
                emit("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            line_end = len(lines)
            emit("")
            result.tables.append(
                ExtractedTable(
                    asset_id=_new_asset_id(),
                    columns=columns,
                    rows=rows,
                    source_ref={
                        "lineStart": line_start,
                        "colStart": 0,
                        "lineEnd": line_end,
                        "colEnd": len(divider),
                    },
                    csv_text=table_to_csv(columns, rows),
                )
            )
            continue

        paragraph = item
        style_level = _style_heading_level(paragraph)
        is_list, list_level = _is_list(paragraph)
        images = _paragraph_images(paragraph, document, len(lines) + 1)
        result.images.extend(images)

        math_markdown: str | None = None
        if _has_math(paragraph):
            xml = etree.tostring(paragraph._p, encoding="unicode")
            math_markdown = convert_paragraph_math(xml)
            result.formulas.append(
                ExtractedFormula(
                    asset_id=_new_asset_id(),
                    latex=math_markdown,
                    original_xml=xml[:20000],
                    source_ref={
                        "lineStart": len(lines) + 1,
                        "colStart": 0,
                        "lineEnd": len(lines) + 1,
                        "colEnd": len(math_markdown or xml[:200]),
                    },
                )
            )
            if not math_markdown:
                result.degraded.append("OMML 公式转换失败，已保留原始 XML 供后续裁图或重试")

        if math_markdown:
            text = math_markdown
        else:
            pieces: list[str] = []
            for run in paragraph.runs:
                pieces.append(_run_text(run))
            text = "".join(pieces).strip() or (paragraph.text or "").strip()
            if _has_math(paragraph) and not math_markdown:
                text = f"{text}（公式，已保留原始 XML 待重试）".strip()

        image_markdown = " ".join(f"![](asset://{image.asset_id})" for image in images)
        combined = " ".join(part for part in (text, image_markdown) if part).strip()

        for image in images:
            image.source_ref["colStart"] = 0
            image.source_ref["colEnd"] = len(combined)

        if not combined:
            if lines and lines[-1] != "":
                emit("")
            continue

        if style_level:
            if lines and lines[-1] != "":
                emit("")
            emit(f"{'#' * style_level} {combined}")
            emit("")
        elif is_list:
            emit(f"{'  ' * list_level}- {combined}")
        else:
            emit(combined)
            emit("")

    markdown = "\n".join(lines).strip() + "\n"
    result.markdown = markdown
    return result