from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.schemas.deck import Deck, DeckMeta
from app.api.schemas.decks import (
    DeckCreate,
    DeckResponse,
    GenerateResponse,
    PatchSubmit,
    RollbackRequest,
    VersionSummary,
)
from app.api.schemas.outline import Outline
from app.core.audit import audit
from app.core.deps import CurrentUser, SessionDep, ensure_owner
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import DeckVersion as DeckVersionRow
from app.db.models import Document
from app.services.deck.versioning import (
    commit_deck_change,
    create_version,
    load_deck_at,
    rollback_to,
)
from app.services.jobs import create_job, enqueue_job
from app.services.theme.manifest import load_manifest, wcag_report

router = APIRouter(prefix="/decks", tags=["decks"])


async def _owned_deck(session: SessionDep, deck_id: UUID, user_id: UUID) -> DeckRow:
    deck = await session.get(DeckRow, deck_id)
    if deck is None or deck.deleted_at is not None:
        raise NotFoundError("演示文稿不存在")
    ensure_owner(deck.user_id, user_id)
    return deck


def _response(payload: dict[str, Any], version_seq: int, theme_id: str) -> DeckResponse:
    slides = payload.get("slides") or []
    degraded = [slide.get("id") for slide in slides if slide.get("degraded")]
    wcag = None
    try:
        wcag = wcag_report(load_manifest(theme_id))
    except Exception:
        wcag = None
    return DeckResponse(
        deck=payload,
        version_seq=version_seq,
        degraded_slides=[slide_id for slide_id in degraded if slide_id],
        wcag=wcag,
    )


@router.post("", response_model=DeckResponse, status_code=201)
async def create_deck(
    payload: DeckCreate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DeckResponse:
    document = await session.get(Document, payload.document_id)
    if document is None:
        raise NotFoundError("文档不存在")
    ensure_owner(document.user_id, user.id)
    if document.status != "ready":
        raise ConflictError("文档尚未完成解析")

    outline_payload = payload.outline
    if outline_payload is None and document.outline:
        outline_payload = Outline.model_validate(document.outline)
    if outline_payload is None:
        raise ConflictError("请先生成并确认大纲")

    try:
        manifest = load_manifest(payload.theme_id)
    except ValidationFailedError as exc:
        raise ValidationFailedError("主题不存在", details=exc.details) from exc

    if document.outline is None or payload.outline is not None:
        from app.services.outline.generator import confirm_outline

        await confirm_outline(session, document, outline_payload)

    deck_row = DeckRow(
        user_id=user.id,
        document_id=document.id,
        title=outline_payload.title,
        theme_id=manifest["id"],
        motion_level=0.0,
    )
    session.add(deck_row)
    await session.flush()

    empty_deck = Deck(
        id=deck_row.id.hex,
        theme_id=deck_row.theme_id,
        meta=DeckMeta(title=outline_payload.title, source_document_id=document.id),
    )
    await create_version(
        session,
        deck_row,
        snapshot=empty_deck.model_dump(mode="json", by_alias=True),
        patch=None,
        kind="anchor",
        label="deck created",
        created_by=user.id,
    )
    await audit(
        session,
        action="deck.create",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck_row.id),
        request=request,
    )
    return _response(empty_deck.model_dump(mode="json", by_alias=True), deck_row.current_version_seq, deck_row.theme_id)


@router.get("", response_model=list[dict[str, Any]])
async def list_decks(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    decks = (
        await session.scalars(
            select(DeckRow)
            .where(DeckRow.user_id == user.id, DeckRow.deleted_at.is_(None))
            .order_by(DeckRow.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": str(deck.id),
            "title": deck.title,
            "themeId": deck.theme_id,
            "motionLevel": deck.motion_level,
            "versionSeq": deck.current_version_seq,
            "documentId": str(deck.document_id) if deck.document_id else None,
            "updatedAt": deck.updated_at.isoformat(),
        }
        for deck in decks
    ]


@router.get("/{deck_id}", response_model=DeckResponse)
async def get_deck(deck_id: UUID, user: CurrentUser, session: SessionDep) -> DeckResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    payload = await load_deck_at(session, deck_row.id, deck_row.current_version_seq)
    return _response(payload, deck_row.current_version_seq, deck_row.theme_id)


@router.post("/{deck_id}/generate", response_model=GenerateResponse, status_code=202)
async def generate_deck(
    deck_id: UUID, user: CurrentUser, session: SessionDep, request: Request
) -> GenerateResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    if deck_row.document_id is None:
        raise ConflictError("该演示文稿没有关联文档")
    document = await session.get(Document, deck_row.document_id)
    if document is None:
        raise NotFoundError("文档不存在")
    if not document.outline:
        raise ConflictError("请先生成并确认大纲")

    job = await create_job(
        session,
        user_id=user.id,
        kind="batch_generate",
        payload={
            "deckId": str(deck_row.id),
            "documentId": str(document.id),
            "outline": document.outline,
        },
        idempotency_key=f"deck:{deck_row.id}:v{deck_row.current_version_seq}",
        max_attempts=2,
    )
    await audit(
        session,
        action="deck.generate",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck_row.id),
        request=request,
        meta={"jobId": str(job.id)},
    )
    await enqueue_job(job.id)
    return GenerateResponse(job_id=job.id, version_seq=deck_row.current_version_seq)


@router.patch("/{deck_id}", response_model=DeckResponse)
async def patch_deck(
    deck_id: UUID,
    payload: PatchSubmit,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DeckResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    version = await commit_deck_change(
        session,
        deck_row,
        payload.operations,
        kind=payload.kind,
        label=payload.label,
        created_by=user.id,
    )
    await audit(
        session,
        action="deck.patch",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck_row.id),
        request=request,
        meta={"seq": version.seq, "ops": len(payload.operations)},
    )
    current = await load_deck_at(session, deck_row.id, deck_row.current_version_seq)
    return _response(current, deck_row.current_version_seq, deck_row.theme_id)


@router.get("/{deck_id}/versions", response_model=list[VersionSummary])
async def list_versions(
    deck_id: UUID, user: CurrentUser, session: SessionDep
) -> list[VersionSummary]:
    deck_row = await _owned_deck(session, deck_id, user.id)
    versions = (
        await session.scalars(
            select(DeckVersionRow)
            .where(DeckVersionRow.deck_id == deck_row.id)
            .order_by(DeckVersionRow.seq.desc())
            .limit(200)
        )
    ).all()
    return [
        VersionSummary(
            id=version.id,
            seq=version.seq,
            parent_id=version.parent_id,
            kind=version.kind,
            label=version.label,
            has_snapshot=version.snapshot is not None,
            created_at=version.created_at.isoformat(),
        )
        for version in versions
    ]


@router.get("/{deck_id}/versions/{seq}", response_model=DeckResponse)
async def get_version(
    deck_id: UUID, seq: int, user: CurrentUser, session: SessionDep
) -> DeckResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    if seq < 1 or seq > deck_row.current_version_seq:
        raise NotFoundError("版本不存在")
    payload = await load_deck_at(session, deck_row.id, seq)
    return _response(payload, seq, deck_row.theme_id)


@router.post("/{deck_id}/rollback", response_model=DeckResponse)
async def rollback(
    deck_id: UUID,
    payload: RollbackRequest,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DeckResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    if payload.target_seq < 1 or payload.target_seq > deck_row.current_version_seq:
        raise NotFoundError("目标版本不存在")
    await rollback_to(session, deck_row, payload.target_seq, created_by=user.id)
    await audit(
        session,
        action="deck.rollback",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck_row.id),
        request=request,
        meta={"targetSeq": payload.target_seq},
    )
    current = await load_deck_at(session, deck_row.id, deck_row.current_version_seq)
    return _response(current, deck_row.current_version_seq, deck_row.theme_id)


@router.put("/{deck_id}/theme", response_model=DeckResponse)
async def change_theme(
    deck_id: UUID,
    theme_id: str,
    user: CurrentUser,
    session: SessionDep,
) -> DeckResponse:
    deck_row = await _owned_deck(session, deck_id, user.id)
    manifest = load_manifest(theme_id)
    await commit_deck_change(
        session,
        deck_row,
        [{"op": "replace", "path": "/themeId", "value": manifest["id"]}],
        kind="milestone",
        label="theme change",
        created_by=user.id,
    )
    deck_row.theme_id = manifest["id"]
    current = await load_deck_at(session, deck_row.id, deck_row.current_version_seq)
    return _response(current, deck_row.current_version_seq, deck_row.theme_id)


@router.delete("/{deck_id}", status_code=204)
async def delete_deck(
    deck_id: UUID, user: CurrentUser, session: SessionDep, request: Request
) -> None:
    deck_row = await _owned_deck(session, deck_id, user.id)
    deck_row.deleted_at = datetime.now(UTC)
    await session.flush()
    await audit(
        session,
        action="deck.soft_delete",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck_row.id),
        request=request,
    )