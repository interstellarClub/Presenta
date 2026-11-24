import asyncio
import hashlib
import re
from typing import Any
from uuid import UUID

import jsonpatch
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Deck, canonical_json
from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import DeckVersion as DeckVersionRow
from app.db.models import Document
from app.services.deck.semantics import ensure_deck_semantics, migrate_deck_payload

ANCHOR_EVERY = 20
_READ_ONLY_PATHS = {"/id", "/schemaVersion", "/meta/sourceDocumentId"}
_SLIDE_INDEX = re.compile(r"^/slides/\d+$")
_SLIDE_CHILD_ID = re.compile(r"^/slides/\d+(/.*/id|/id)$")
_COMMIT_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def _deck_lock(deck_id: UUID) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), str(deck_id))
    lock = _COMMIT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _COMMIT_LOCKS[key] = lock
    return lock


def _is_layout_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return len(parts) == 3 and parts[0] == "slides" and parts[2] == "layout"


def _is_read_only(path: str) -> bool:
    if path in _READ_ONLY_PATHS:
        return True
    if _is_layout_path(path):
        return True
    return bool(_SLIDE_CHILD_ID.match(path))


def validate_operations(operations: list[dict[str, Any]]) -> None:
    if not operations:
        raise ValidationFailedError("patch must contain at least one operation")
    if len(operations) > settings.max_patch_ops:
        raise ValidationFailedError(f"patch exceeds {settings.max_patch_ops} operations")
    for operation in operations:
        if not isinstance(operation, dict) or "op" not in operation or "path" not in operation:
            raise ValidationFailedError("each patch operation requires op and path")
        op = str(operation["op"])
        path = str(operation["path"])
        if _is_read_only(path):
            raise ValidationFailedError(f"字段只读，禁止 Patch 修改：{path}")
        if path.startswith("/slides/-"):
            raise ValidationFailedError("禁止向 slides 追加页面")
        if op in {"add", "remove", "move", "copy"} and (
            path == "/slides" or _SLIDE_INDEX.match(path)
        ):
            raise ValidationFailedError("禁止通过 Patch 新增或删除整页，请使用生成/回退流程")
        if op in {"move", "copy"} and path.startswith("/slides"):
            raise ValidationFailedError("禁止移动或复制页面数组元素")


def _slide_identity(payload: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(slide.get("id")), str(slide.get("layout")))
        for slide in payload.get("slides") or []
        if isinstance(slide, dict)
    ]


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


async def _document_for(
    session: AsyncSession, deck_row: DeckRow, document: Document | None
) -> Document | None:
    if document is not None:
        return document
    if deck_row.document_id is None:
        return None
    return await session.get(Document, deck_row.document_id)


async def _next_seq(session: AsyncSession, deck_id: UUID) -> int:
    current_max = await session.scalar(
        select(func.max(DeckVersionRow.seq)).where(DeckVersionRow.deck_id == deck_id)
    )
    return int(current_max or 0) + 1


async def create_version(
    session: AsyncSession,
    deck_row: DeckRow,
    *,
    snapshot: dict[str, Any],
    patch: list[dict[str, Any]] | None = None,
    kind: str = "autosave",
    label: str | None = None,
    created_by: UUID | None = None,
    document: Document | None = None,
) -> DeckVersionRow:
    deck = Deck.model_validate(snapshot)
    resolved_document = await _document_for(session, deck_row, document)
    await ensure_deck_semantics(
        session,
        deck,
        document=resolved_document,
        require_non_empty=False,
        expected_deck_id=deck_row.id.hex,
    )

    seq = await _next_seq(session, deck_row.id)
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
    parent: DeckVersionRow | None = None
    if deck_row.current_version_seq > 0:
        parent = await session.scalar(
            select(DeckVersionRow).where(
                DeckVersionRow.deck_id == deck_row.id,
                DeckVersionRow.seq == deck_row.current_version_seq,
            )
        )
    if parent is not None:
        version.parent_id = parent.id
    session.add(version)
    deck_row.current_version_seq = seq
    await session.flush()
    return version


async def _version_at(
    session: AsyncSession, deck_id: UUID, seq: int
) -> DeckVersionRow | None:
    return await session.scalar(
        select(DeckVersionRow).where(
            DeckVersionRow.deck_id == deck_id, DeckVersionRow.seq == seq
        )
    )


async def load_deck_at(session: AsyncSession, deck_id: UUID, seq: int) -> dict[str, Any]:
    target = await _version_at(session, deck_id, seq)
    if target is None:
        raise NotFoundError("版本不存在")

    chain: list[DeckVersionRow] = [target]
    node: DeckVersionRow = target
    while node.snapshot is None:
        if node.parent_id is None:
            raise NotFoundError("no snapshot available on this branch")
        parent = await session.get(DeckVersionRow, node.parent_id)
        if parent is None or parent.deck_id != deck_id:
            raise NotFoundError("broken version parent chain")
        node = parent
        chain.append(node)
        if len(chain) > ANCHOR_EVERY * 2 + 5:
            raise NotFoundError("version chain is too deep")

    payload = node.snapshot
    if payload is None:
        raise NotFoundError("no snapshot available on this branch")
    for ancestor in reversed(chain[:-1]):
        if ancestor.snapshot is not None:
            payload = ancestor.snapshot
        elif ancestor.patch:
            payload = apply_patch_payload(payload, ancestor.patch)
    return migrate_deck_payload(payload)


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
    document: Document | None = None,
    expected_seq: int | None = None,
) -> DeckVersionRow:
    if settings.uses_sqlite:
        async with _deck_lock(deck_row.id):
            return await _commit_deck_change_locked(
                session,
                deck_row,
                operations,
                kind=kind,
                label=label,
                created_by=created_by,
                document=document,
                expected_seq=expected_seq,
            )
    return await _commit_deck_change_locked(
        session,
        deck_row,
        operations,
        kind=kind,
        label=label,
        created_by=created_by,
        document=document,
        expected_seq=expected_seq,
    )


async def _commit_deck_change_locked(
    session: AsyncSession,
    deck_row: DeckRow,
    operations: list[dict[str, Any]],
    *,
    kind: str,
    label: str | None,
    created_by: UUID | None,
    document: Document | None,
    expected_seq: int | None,
) -> DeckVersionRow:
    await session.refresh(deck_row)
    if expected_seq is not None and deck_row.current_version_seq != expected_seq:
        raise ConflictError(
            "版本已被其他编辑更新，请刷新后重试",
            details={
                "expectedSeq": expected_seq,
                "currentSeq": deck_row.current_version_seq,
            },
        )
    current = await load_current_deck(session, deck_row)
    before = current.model_dump(mode="json", by_alias=True)
    after = apply_patch_payload(before, operations)
    if _slide_identity(before) != _slide_identity(after):
        raise ValidationFailedError(
            "Patch 不得改变页面数量、页面 id 或版式骨架（layout 只读）"
        )
    deck = Deck.model_validate(after)
    resolved_document = await _document_for(session, deck_row, document)
    await ensure_deck_semantics(
        session,
        deck,
        document=resolved_document,
        require_non_empty=True,
        expected_deck_id=deck_row.id.hex,
    )
    snapshot = deck.model_dump(mode="json", by_alias=True)
    return await create_version(
        session,
        deck_row,
        snapshot=snapshot,
        patch=operations,
        kind=kind,
        label=label,
        created_by=created_by,
        document=resolved_document,
    )


async def rollback_to(
    session: AsyncSession,
    deck_row: DeckRow,
    target_seq: int,
    *,
    document: Document | None = None,
) -> int:
    payload = await load_deck_at(session, deck_row.id, target_seq)
    deck = Deck.model_validate(payload)
    if not deck.slides:
        raise ConflictError("不能回退到空 Deck（尚未生成页面）")
    resolved_document = await _document_for(session, deck_row, document)
    await ensure_deck_semantics(
        session,
        deck,
        document=resolved_document,
        require_non_empty=True,
        expected_deck_id=deck_row.id.hex,
    )
    deck_row.current_version_seq = target_seq
    await session.flush()
    return target_seq


def deck_payload(deck: Deck) -> dict[str, Any]:
    return deck.model_dump(mode="json", by_alias=True)


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()