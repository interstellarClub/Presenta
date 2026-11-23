import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.outline import Outline, OutlineItem
from app.core.errors import ValidationFailedError
from app.db.models import Document
from app.services.ingest.markdown import sections_for_outline
from app.services.llm.gateway import generate_structured
from app.services.llm.prompts import load_prompt, render

MAX_PROMPT_SECTIONS = 60


def outline_context(document: Document) -> dict[str, Any]:
    ast = document.ast or {}
    sections = sections_for_outline(ast)[:MAX_PROMPT_SECTIONS]
    return {
        "documentTitle": document.title,
        "sections": [
            {
                "id": section["id"],
                "title": section["title"],
                "summary": section["summary"],
                "text": section["text"],
                "level": section["level"],
            }
            for section in sections
        ],
    }


def _prompt_sections(context: dict[str, Any]) -> str:
    payload = [
        {
            "id": section["id"],
            "title": section["title"],
            "summary": section["summary"],
        }
        for section in context["sections"]
    ]
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _sanitize(outline: Outline, known_ids: set[str]) -> Outline:
    items: list[OutlineItem] = []
    for index, item in enumerate(outline.items):
        section_id = item.section_id if item.section_id in known_ids else None
        items.append(
            OutlineItem(
                id=item.id or f"item-{index + 1}",
                title=item.title,
                points=item.points,
                section_id=section_id,
                layout_hint=item.layout_hint,
            )
        )
    if not items:
        raise ValidationFailedError("outline produced no items")
    payload = outline.model_dump()
    payload["items"] = [item.model_dump() for item in items]
    return Outline.model_validate(payload)


async def generate_outline(
    session: AsyncSession,
    document: Document,
    *,
    user_id: UUID | None = None,
) -> Outline:
    context = outline_context(document)
    if not context["sections"]:
        raise ValidationFailedError("document has no parsed sections")

    system_prompt = load_prompt("outline", "outline")
    user_prompt = render(
        system_prompt,
        document_title=document.title,
        section_count=str(len(context["sections"])),
        sections=_prompt_sections(context),
    )
    outline = await generate_structured(
        session,
        purpose="outline",
        schema=Outline,
        system_prompt="你只输出严格符合要求的 JSON 对象。",
        user_prompt=user_prompt,
        mock_context=context,
        user_id=user_id,
        thinking=True,
        temperature=0.3,
    )
    return _sanitize(outline, {section["id"] for section in context["sections"]})


async def stream_outline(
    session: AsyncSession,
    document: Document,
    *,
    user_id: UUID | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    context = outline_context(document)
    yield "stage", {"stage": "summarizing", "sections": len(context["sections"])}
    outline = await generate_outline(session, document, user_id=user_id)
    yield "stage", {"stage": "drafting", "items": len(outline.items)}
    for item in outline.items:
        yield "item", item.model_dump(mode="json", by_alias=True)
    yield "done", outline.model_dump(mode="json", by_alias=True)


async def confirm_outline(session: AsyncSession, document: Document, outline: Outline) -> None:
    ast = document.ast or {}
    known_ids = {section["id"] for section in ast.get("sections", [])}
    sanitized = _sanitize(outline, known_ids)
    document.outline = sanitized.model_dump(mode="json", by_alias=True)
    await session.flush()
    await session.refresh(document)