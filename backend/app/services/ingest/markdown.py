import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LIST_TAGS = {"bullet_list_open", "ordered_list_open"}


@dataclass
class HeadingMark:
    level: int
    title: str
    start_line: int
    order: int


@dataclass
class SectionDraft:
    id: str
    title: str
    level: int
    start_line: int
    end_line: int
    parent_id: str | None = None
    blocks: list[int] = field(default_factory=list)


def _parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
    parser.enable("table")
    parser.enable("strikethrough")
    return parser


def _line_offsets(md: str) -> tuple[list[str], list[int]]:
    lines = md.splitlines()
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    return lines, offsets


def _plain_text(inline_token: Any) -> str:
    if inline_token is None:
        return ""
    children = getattr(inline_token, "children", None) or []
    if children:
        parts = [
            child.content
            for child in children
            if child.type in {"text", "code_inline", "math_inline"}
        ]
        if parts:
            return "".join(parts).strip()
    return str(inline_token.content or "").strip()


def _collect_tables(tokens: list[Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != "table_open":
            index += 1
            continue
        rows: list[list[str]] = []
        current: list[str] = []
        cell_text: list[str] = []
        while index < len(tokens) and tokens[index].type != "table_close":
            tok = tokens[index]
            if tok.type == "tr_open":
                current = []
            elif tok.type in {"th_open", "td_open"}:
                cell_text = []
            elif tok.type == "inline":
                cell_text.append(_plain_text(tok))
            elif tok.type in {"th_close", "td_close"}:
                current.append(" ".join(part for part in cell_text if part).strip())
            elif tok.type == "tr_close":
                if current:
                    rows.append(current)
            index += 1
        line_map = token.map or [0, 0]
        tables.append(
            {
                "rows": rows,
                "lineStart": line_map[0] + 1,
                "lineEnd": line_map[1],
            }
        )
        index += 1
    return tables


def build_ast(md: str) -> dict[str, Any]:
    parser = _parser()
    tokens = parser.parse(md)
    lines, offsets = _line_offsets(md)

    headings: list[HeadingMark] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open" and token.tag in _HEADING_TAGS:
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            start = (token.map or [0, 0])[0]
            headings.append(
                HeadingMark(
                    level=_HEADING_TAGS[token.tag],
                    title=_plain_text(inline),
                    start_line=start,
                    order=len(headings),
                )
            )
        index += 1

    total_lines = max(1, len(lines))
    sections: list[SectionDraft] = []
    stack: list[SectionDraft] = []
    for order, mark in enumerate(headings):
        end_line = total_lines
        for later in headings[order + 1 :]:
            if later.level <= mark.level:
                end_line = later.start_line
                break
        while stack and stack[-1].level >= mark.level:
            stack.pop()
        section = SectionDraft(
            id=f"sec-{len(sections) + 1:03d}",
            title=mark.title or f"第 {len(sections) + 1} 节",
            level=mark.level,
            start_line=mark.start_line,
            end_line=end_line,
            parent_id=stack[-1].id if stack else None,
        )
        sections.append(section)
        stack.append(section)

    if not sections:
        sections.append(
            SectionDraft(
                id="sec-001",
                title="全文",
                level=1,
                start_line=0,
                end_line=total_lines,
            )
        )

    blocks: list[dict[str, Any]] = []
    for token in tokens:
        if token.level != 0 or not token.map:
            continue
        start, end = token.map
        block: dict[str, Any] = {
            "index": len(blocks),
            "type": token.type,
            "tag": token.tag,
            "lineStart": start + 1,
            "lineEnd": max(start + 1, end),
            "charStart": offsets[min(start, len(offsets) - 1)],
            "charEnd": offsets[min(end, len(offsets) - 1)],
            "sectionId": None,
        }
        for section in sections:
            if section.start_line <= start < section.end_line:
                block["sectionId"] = section.id
                section.blocks.append(block["index"])
                break
        blocks.append(block)

    payload_sections: list[dict[str, Any]] = []
    for section in sections:
        text = "\n".join(lines[section.start_line : section.end_line]).strip()
        payload_sections.append(
            {
                "id": section.id,
                "title": section.title,
                "level": section.level,
                "parentId": section.parent_id,
                "lineStart": section.start_line + 1,
                "lineEnd": section.end_line,
                "charStart": offsets[min(section.start_line, len(offsets) - 1)],
                "charEnd": offsets[min(section.end_line, len(offsets) - 1)],
                "text": text,
                "words": len(re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]", text)),
            }
        )

    return {
        "version": 1,
        "lineCount": total_lines,
        "sections": payload_sections,
        "blocks": blocks,
        "tables": _collect_tables(tokens),
    }


def summarize_section(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    clipped = compact[:limit]
    cut = max(clipped.rfind("。"), clipped.rfind("."), clipped.rfind("；"), clipped.rfind(";"))
    if cut >= limit // 2:
        return clipped[: cut + 1]
    return clipped.rstrip() + "…"


def sections_for_outline(ast: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for section in ast.get("sections", []):
        result.append(
            {
                "id": section["id"],
                "title": section["title"],
                "level": section["level"],
                "summary": summarize_section(section.get("text", "")),
                "text": section.get("text", "")[:4000],
            }
        )
    return result


def strip_markdown(md: str) -> str:
    text = re.sub(r"```.*?```", " ", md, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~|-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()