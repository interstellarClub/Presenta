from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.exports import ExportArtifactView, ExportRequest, ExportStart
from app.core.deps import CurrentUser, SessionDep, ensure_owner
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Deck as DeckRow
from app.db.models import ExportArtifact
from app.services.export.service import create_export, list_artifacts
from app.services.jobs import create_job, enqueue_job
from app.services.storage import storage

router = APIRouter(prefix="/exports", tags=["exports"])

JOB_KIND = {"pdf": "pdf_export", "gif": "gif_export", "pptx": "ppt_export"}
_EXT = {"pdf": "pdf", "pptx": "pptx", "gif": "gif", "html": "html"}


def _view(artifact: ExportArtifact) -> ExportArtifactView:
    return ExportArtifactView(
        id=artifact.id,
        format=artifact.format,
        bytes=artifact.bytes,
        degraded=artifact.degraded,
        degraded_notes=list(artifact.degraded_notes or []),
        download_url=f"/api/exports/{artifact.id}/download",
        expires_at=artifact.expires_at.isoformat(),
    )


async def _owned_deck(session: AsyncSession, deck_id: UUID, user_id: UUID) -> DeckRow:
    deck = await session.get(DeckRow, deck_id)
    if deck is None or deck.deleted_at is not None:
        raise NotFoundError("演示文稿不存在")
    ensure_owner(deck.user_id, user_id)
    return deck


@router.post("", response_model=ExportStart, status_code=202)
async def start_export(
    payload: ExportRequest,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> ExportStart:
    deck = await _owned_deck(session, payload.deck_id, user.id)
    if payload.format == "mp4":
        raise ConflictError(
            "MP4 走客户端 WebCodecs 管线，不提供服务端导出；请使用播放页的「导出视频」。"
        )

    if payload.format == "html":
        artifact, cached = await create_export(
            session,
            deck_row=deck,
            user_id=user.id,
            fmt="html",
            options=payload.options,
        )
        return ExportStart(artifact=_view(artifact), cached=cached)

    kind = JOB_KIND[payload.format]
    job = await create_job(
        session,
        user_id=user.id,
        kind=kind,
        payload={
            "deckId": str(deck.id),
            "versionSeq": deck.current_version_seq,
            "options": payload.options,
        },
        max_attempts=2,
    )
    from app.core.audit import audit

    await audit(
        session,
        action="export.start",
        user_id=user.id,
        target_type="deck",
        target_id=str(deck.id),
        request=request,
        meta={"format": payload.format, "jobId": str(job.id)},
    )
    await enqueue_job(job.id)
    return ExportStart(job_id=job.id)


@router.get("", response_model=list[ExportArtifactView])
async def list_exports(
    user: CurrentUser,
    session: SessionDep,
    deck_id: Annotated[UUID, Query(alias="deckId")],
) -> list[ExportArtifactView]:
    deck = await _owned_deck(session, deck_id, user.id)
    artifacts = await list_artifacts(session, deck.id, owner=user.id)
    return [_view(artifact) for artifact in artifacts]


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID, user: CurrentUser, session: SessionDep
) -> Response:
    artifact = await session.get(ExportArtifact, artifact_id)
    if artifact is None:
        raise NotFoundError("导出物不存在")
    ensure_owner(artifact.user_id, user.id)
    data = await storage.get_bytes(artifact.storage_key)
    filename = f"presenta-{artifact.deck_id}-v{artifact.version_id}.{_EXT.get(artifact.format, 'bin')}"
    return Response(
        content=data,
        media_type={
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "gif": "image/gif",
            "html": "text/html; charset=utf-8",
        }.get(artifact.format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.get("/{artifact_id}", response_model=ExportArtifactView)
async def get_artifact(
    artifact_id: UUID, user: CurrentUser, session: SessionDep
) -> ExportArtifactView:
    artifact = await session.get(ExportArtifact, artifact_id)
    if artifact is None:
        raise NotFoundError("导出物不存在")
    ensure_owner(artifact.user_id, user.id)
    return _view(artifact)