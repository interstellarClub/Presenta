from typing import Any
from uuid import UUID

import jsonpatch
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Deck, canonical_json
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import DeckVersion as DeckVersionRow

ANCHOR_EVERY = 20
IMMUTABLE_PREFIXES = ("/id", "/schemaVersion", "/slides/")


def _is_layout_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return len(parts) == 3 and parts[0] == "slides" and parts[2] == "layout"


def _is_slide_id_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return len(parts) == 3 and parts[0] == "slides" and parts[2] == "id"


def validate_operations(operations: list[dict[str, Any]]) -> None:
    if len(operations) > settings.max_patch_ops:
        raise ValidationFailedError(f"patch exceeds {settings.max_patch_ops} operations")
    for op in operations:
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise ValidationFailedError("each patch operation requires op and path")
        path = str(op["path"])
        if _is_layout_path(path) or _is_slide_id_path(path):
            raise ValidationFailedError("layout and slide id are read-only")
        if path.startswith("/slides/-"):
            raise ValidationFailedError("array append is not allowed on slides")


def apply_patch_payload(payload: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    validate_operations(operations)
    try:
        result = jsonpatch.JsonPatch(operations).apply(payload, in_place=False)
    except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException) as exc:
        raise ValidationFailedError("patch could not be applied", details={"error": str(exc)}) from exc
    try:
        return Deck.model_validate(result).model_dump(mode="json", by_alias=True)
    except ValidationError as exc:
        raise ValidationFailedError(
            "patched deck failed schema validation",
            details={"errors": exc.errors(include_url=False)},
        ) from exc


async def create_version(
    session: AsyncSession,
    deck_row: DeckRow,
    *,
    snapshot: dict[str, Any],
    patch: list[dict[str, Any]] | None = None,
    kind: str = "autosave",
    label: str | None = None,
    created_by: UUID | None = None,
) -> DeckVersionRow:
    seq = deck_row.current_version_seq + 1
    is_anchor_seq = seq % ANCHOR_EVERY == 0
    includes_snapshot = kind in {"anchor", "milestone"} or is_anchor_seq or patch is None


    version = DeckVersionRow(
        deck_id=deck_row.id,
        seq=seq,
        kind=kind,
        label=label,
        patch=patch,
        snapshot=snapshot if includes_snapshot else None,
        created_by=created_by,
    )
    parent = await session.scalar(
        select(DeckVersionRow).where(
            DeckVersionRow.deck_id == deck_row.id, DeckVersionRow.seq == seq - 1
        )
    )
    if parent is not None:
        version.parent_id = parent.id
    session.add(version)
    deck_row.current_version_seq = seq
    await session.flush()
    return version


async def load_deck_at(session: AsyncSession, deck_id: UUID, seq: int) -> dict[str, Any]:
    candidates = (
        await session.scalars(
            select(DeckVersionRow)
            .where(DeckVersionRow.deck_id == deck_id, DeckVersionRow.seq <= seq)
            .order_by(DeckVersionRow.seq.desc())
            .limit(ANCHOR_EVERY + 5)
        )
    ).all()
    anchor = next((row for row in candidates if row.snapshot is not None), None)
    if anchor is None or anchor.snapshot is None:
        raise NotFoundError("no snapshot available for this deck")

    payload = anchor.snapshot
    current_seq = anchor.seq
    chain = (
        await session.scalars(
            select(DeckVersionRow)
            .where(
                DeckVersionRow.deck_id == deck_id,
                DeckVersionRow.seq > current_seq,
                DeckVersionRow.seq <= seq,
            )
            .order_by(DeckVersionRow.seq.asc())
        )
    ).all()
    for version in chain:
        if version.snapshot is not None:
            payload = version.snapshot
        elif version.patch:
            payload = apply_patch_payload(payload, version.patch)
    return payload


async def load_current_deck(session: AsyncSession, deck_row: DeckRow) -> Deck:
    payload = await load_deck_at(session, deck_row.id, deck_row.current_version_seq)
    return Deck.model_validate(payload)


async def commit_deck_change(
    session: AsyncSession,
    deck_row: DeckRow,
    operations: list[dict[str, Any]],
    *,
    kind: str = "autosave",
    label: str | None = None,
    created_by: UUID | None = None,
) -> DeckVersionRow:
    current = await load_current_deck(session, deck_row)
    before = current.model_dump(mode="json", by_alias=True)
    after = apply_patch_payload(before, operations)
    snapshot = Deck.model_validate(after).model_dump(mode="json", by_alias=True)
    return await create_version(
        session,
        deck_row,
        snapshot=snapshot,
        patch=operations,
        kind=kind,
        label=label,
        created_by=created_by,
    )


async def rollback_to(
    session: AsyncSession,
    deck_row: DeckRow,
    target_seq: int,
    *,
    created_by: UUID | None = None,
) -> DeckVersionRow:
    current = await load_current_deck(session, deck_row)
    target_payload = await load_deck_at(session, deck_row.id, target_seq)
    target = Deck.model_validate(target_payload)
    operations = jsonpatch.make_patch(
        current.model_dump(mode="json", by_alias=True),
        target.model_dump(mode="json", by_alias=True),
    ).patch
    new_snapshot = target.model_dump(mode="json", by_alias=True)
    return await create_version(
        session,
        deck_row,
        snapshot=new_snapshot,
        patch=operations,
        kind="milestone",
        label=f"rollback to v{target_seq}",
        created_by=created_by,
    )


def deck_payload(deck: Deck) -> dict[str, Any]:
    return deck.model_dump(mode="json", by_alias=True)


def payload_hash(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()