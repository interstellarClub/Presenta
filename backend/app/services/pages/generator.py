import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Deck, DeckMeta, Provenance, Slide
from app.api.schemas.outline import Outline
from app.api.schemas.pages import PageDraft, draft_to_slide
from app.core.errors import ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import DeckVersion as DeckVersionRow
from app.db.models import DocAsset, Document
from app.services.deck.layouts import LAYOUTS, display_width, layout_catalog_for_prompt
from app.services.deck.versioning import create_version
from app.services.ingest.markdown import summarize_section
from app.services.llm.gateway import generate_structured
from app.services.llm.prompts import load_prompt, render
from app.services.pages.validator import (
    attach_section_provenance,
    semantic_issues,
)

PAGE_ATTEMPTS = 2
MAX_SECTION_CHARS = 6000


class JobCancelled(Exception):
    pass


def _truncate(text: str, limit: int) -> str:
    if display_width(text) <= limit:
        return text
    out: list[str] = []
    budget = 0.0
    for char in text:
        width = display_width(char)
        if budget + width > limit:
            break
        budget += width
        out.append(char)
    return "".join(out).rstrip("，。；,.;")


def _sentences(text: str, limit: int = 6) -> list[str]:
    import re

    parts = re.split(r"(?<=[。！？!?；;\.])\s*", " ".join(text.split()))
    return [part.strip("。；;. ") for part in parts if part.strip("。；;. ")][:limit]


def degraded_slide(
    *, title: str, section_text: str, reason: str, slide_id: str | None = None
) -> Slide:
    safe_title = _truncate(title or "未命名页面", 24) or "未命名页面"
    sentences = [_truncate(sentence, 36) for sentence in _sentences(section_text, 3) if sentence]
    filler = "详见原文，请手动完善此页"
    while len(sentences) < 3:
        sentences.append(filler)
    return Slide(
        id=slide_id or uuid.uuid4().hex[:12],
        layout="bullets",
        slots={
            "title": safe_title,
            "lead": _truncate(summarize_section(section_text, 60), 60),
            "items": sentences[:3],
        },
        notes="",
        degraded=True,
        degraded_reason=_truncate(reason, 200),
    )


def _resolve_section(
    sections: list[dict[str, Any]], item_index: int, section_id: str | None
) -> dict[str, Any]:
    if section_id:
        for section in sections:
            if section.get("id") == section_id:
                return section
    if not sections:
        return {"id": None, "title": "全文", "text": "", "lineStart": 1, "lineEnd": 1}
    return sections[min(item_index, len(sections) - 1)]


def _allowed_layouts(index: int, total: int) -> list[str]:
    if index == 0:
        return ["cover", "bullets", "split-lr", "big-number"]
    if index == total - 1 and total >= 3:
        return ["ending", "quote", "bullets"]
    if index == 1 and total > 4:
        return ["toc", "bullets", "cards-3", "timeline", "process"]
    return [
        layout_id
        for layout_id in LAYOUTS
        if layout_id not in {"cover", "ending", "toc"}
    ]


async def _asset_payload(session: AsyncSession, document_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(DocAsset)
            .where(DocAsset.document_id == document_id)
            .order_by(DocAsset.kind, DocAsset.created_at)
            .limit(24)
        )
    ).all()
    payload: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "assetId": row.id.hex,
            "kind": row.kind,
            "mime": row.mime,
            "sourceRef": row.source_ref,
        }
        if row.kind == "image":
            entry["width"] = row.width_px
            entry["height"] = row.height_px
            entry["name"] = (row.meta or {}).get("name")
        elif row.kind == "table":
            meta = row.meta or {}
            entry["columns"] = meta.get("columns")
            entry["rows"] = (meta.get("rows") or [])[:8]
        elif row.kind == "formula":
            entry["latex"] = (row.meta or {}).get("latex")
        payload.append(entry)
    return payload


def _page_prompt(
    *,
    document: Document,
    outline: Outline,
    item_index: int,
    item_title: str,
    points: list[str],
    section: dict[str, Any],
    allowed_layouts: list[str],
    assets: list[dict[str, Any]],
) -> tuple[str, str]:
    template = load_prompt("pages", "page")
    system_prompt = render(template, layout_catalog=layout_catalog_for_prompt())
    source_ref = {
        "lineStart": section.get("lineStart"),
        "lineEnd": section.get("lineEnd"),
    }
    user_prompt = (
        f"文稿标题：{outline.title}\n"
        f"页码：{item_index + 1} / {len(outline.items)}\n"
        f"页面标题候选：{item_title}\n"
        f"该页要点：{json.dumps(points, ensure_ascii=False)}\n"
        f"允许版式 id：{json.dumps(allowed_layouts)}\n"
        f"章节 id：{section.get('id')}\n"
        f"原文定位：{json.dumps(source_ref, ensure_ascii=False)}\n"
        f"文档 id：{document.id}\n"
        f"原始正文（节选）：\n{str(section.get('text') or '')[:MAX_SECTION_CHARS]}\n"
        f"可用资产（JSON）：\n{json.dumps(assets, ensure_ascii=False)[:4000]}\n"
        "请只输出 JSON。"
    )
    return system_prompt, user_prompt


async def generate_pages(
    session: AsyncSession,
    *,
    deck_row: DeckRow,
    document: Document,
    outline: Outline,
    user_id: UUID | None = None,
    job_id: UUID | None = None,
    progress: Callable[[int, str], Awaitable[None]] | None = None,
    check_cancel: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[Deck, list[DeckVersionRow]]:
    ast = document.ast or {}
    sections = ast.get("sections") or []
    document_text = document.normalized_md or ""
    assets = await _asset_payload(session, document.id)
    slides: list[Slide] = []
    degraded_count = 0

    for index, item in enumerate(outline.items):
        if check_cancel is not None and await check_cancel():
            raise JobCancelled("job cancelled by user")
        section = _resolve_section(sections, index, item.section_id)
        allowed = _allowed_layouts(index, len(outline.items))
        system_prompt, user_prompt = _page_prompt(
            document=document,
            outline=outline,
            item_index=index,
            item_title=item.title,
            points=item.points,
            section=section,
            allowed_layouts=allowed,
            assets=assets,
        )
        mock_context = {
            "documentTitle": document.title,
            "total": len(outline.items),
            "outlineItems": [entry.model_dump(by_alias=True) for entry in outline.items],
            "section": {
                "index": index,
                "title": item.title,
                "text": str(section.get("text") or ""),
                "summary": summarize_section(str(section.get("text") or "")),
                "id": section.get("id"),
            },
        }

        slide: Slide | None = None
        issues: list[str] = []
        for attempt in range(PAGE_ATTEMPTS):
            prompt = user_prompt
            if attempt > 0 and issues:
                repair = load_prompt("pages", "repair")
                errors_text = "\n".join(issues)
                prompt = user_prompt + "\n\n" + render(
                    repair, errors=errors_text, previous_json=""
                )
            try:
                draft: PageDraft = await generate_structured(
                    session,
                    purpose="page",
                    schema=PageDraft,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    mock_context=mock_context,
                    user_id=user_id,
                    deck_id=deck_row.id,
                    job_id=job_id,
                    thinking=True,
                    temperature=0.2,
                )
                candidate = draft_to_slide(draft)
                if candidate.layout not in allowed:
                    issues = [f"版式 '{candidate.layout}' 不在本页允许列表"]
                    continue
                attach_section_provenance(candidate, section, document.id, document_text)
                issues = await semantic_issues(
                    session,
                    candidate,
                    document_id=document.id,
                    document_text=document_text,
                )
                if not issues:
                    slide = candidate
                    break
            except ValidationFailedError as exc:
                issues = [str(exc)]

        if slide is None:
            degraded_count += 1
            slide = degraded_slide(
                title=item.title,
                section_text=str(section.get("text") or ""),
                reason="；".join(issues) or "模型输出未通过校验",

            )
        slides.append(slide)

        if progress is not None:
            percent = int((index + 1) / max(1, len(outline.items)) * 100)
            await progress(percent, f"generating({index + 1}/{len(outline.items)})")

    provenance: list[Provenance] = [entry for slide in slides for entry in slide.provenance]
    deck = Deck(
        id=deck_row.id.hex,
        theme_id=deck_row.theme_id,
        motion_level=deck_row.motion_level,
        meta=DeckMeta(
            title=outline.title,
            subtitle=outline.subtitle,
            source_document_id=document.id,
        ),
        slides=slides,
        provenance=provenance,
    )
    deck_row.title = outline.title
    snapshot = deck.model_dump(mode="json", by_alias=True)
    version = await create_version(
        session,
        deck_row,
        snapshot=snapshot,
        patch=None,
        kind="milestone",
        label="initial generation",
        created_by=user_id,
    )
    return deck, [version]