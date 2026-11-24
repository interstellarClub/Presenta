import json
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import CamelModel, Deck
from app.core.errors import ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import Document
from app.services.deck.semantics import ensure_deck_semantics
from app.services.deck.versioning import load_current_deck
from app.services.llm.gateway import generate_structured
from app.services.llm.prompts import load_prompt, render


class IntentPatch(CamelModel):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    explanation: str = Field(default="", max_length=300)


async def generate_intent_patch(
    session: AsyncSession,
    *,
    deck_row: DeckRow,
    instruction: str,
    user_id: UUID,
) -> tuple[list[dict[str, Any]], str]:
    current: Deck = await load_current_deck(session, deck_row)
    system_prompt = load_prompt("intent", "edit")
    user_prompt = render(
        load_prompt("intent", "edit_user"),
        instruction=instruction,
        deck_json=json.dumps(
            current.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )[:30000],
    )
    draft = await generate_structured(
        session,
        purpose="intent",
        schema=IntentPatch,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        mock_context={
            "candidate_patch": [],
            "current_motion_level": current.motion_level,
        },
        user_id=user_id,
        deck_id=deck_row.id,
        thinking=False,
        temperature=0.1,
        repair_budget=2,
    )
    from app.services.deck.versioning import apply_patch_payload, validate_operations

    validate_operations(draft.operations)
    preview = Deck.model_validate(
        apply_patch_payload(current.model_dump(mode="json", by_alias=True), draft.operations)
    )
    document = (
        await session.get(Document, deck_row.document_id) if deck_row.document_id else None
    )
    try:
        await ensure_deck_semantics(
            session,
            preview,
            document=document,
            require_non_empty=True,
            expected_deck_id=deck_row.id.hex,
        )
    except ValidationFailedError as exc:
        raise ValidationFailedError(
            "自然语言生成的 Patch 未通过语义校验",
            details=exc.details,
        ) from exc
    return draft.operations, draft.explanation
