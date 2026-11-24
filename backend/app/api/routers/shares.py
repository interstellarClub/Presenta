from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.api.schemas.deck import Deck
from app.api.schemas.shares import (
    GuestDownload,
    GuestInfo,
    ShareCreate,
    ShareView,
    UnlockRequest,
    UnlockResponse,
)
from app.core.audit import audit
from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep, ensure_owner
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Deck as DeckRow
from app.db.models import ExportArtifact, Share
from app.services.deck.versioning import load_deck_at
from app.services.export.service import create_export
from app.services.share import service as share_service
from app.services.storage import storage

router = APIRouter(prefix="/shares", tags=["shares"])


def _view(share: Share) -> ShareView:
    return ShareView(
        id=share.id,
        slug=share.slug,
        url=f"/s/{share.slug}",
        expires_at=share.expires_at,
        allow_download=share.allow_download,
        download_formats=list(share.download_formats or []),
        view_count=share.view_count,
        revoked_at=share.revoked_at,
    )


async def _owned_share(session: SessionDep, share_id: UUID, user_id: UUID) -> Share:
    share = await session.get(Share, share_id)
    if share is None:
        raise NotFoundError("分享不存在")
    ensure_owner(share.created_by, user_id)
    return share


@router.post("", response_model=ShareView, status_code=201)
async def create_share(
    payload: ShareCreate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> ShareView:
    deck = await session.get(DeckRow, payload.deck_id)
    if deck is None or deck.deleted_at is not None:
        raise NotFoundError("演示文稿不存在")
    ensure_owner(deck.user_id, user.id)
    share = await share_service.create_share(
        session,
        deck=deck,
        created_by=user.id,
        password=payload.password,
        ttl_hours=payload.ttl_hours,
        allow_download=payload.allow_download,
        formats=payload.formats,
    )
    await audit(
        session,
        action="share.create",
        user_id=user.id,
        target_type="share",
        target_id=str(share.id),
        request=request,
        meta={"deckId": str(deck.id)},
    )
    return _view(share)


@router.get("", response_model=list[ShareView])
async def list_shares(
    user: CurrentUser,
    session: SessionDep,
    deck_id: Annotated[UUID, Query(alias="deckId")],
) -> list[ShareView]:
    deck = await session.get(DeckRow, deck_id)
    if deck is None:
        raise NotFoundError("演示文稿不存在")
    ensure_owner(deck.user_id, user.id)
    rows = (
        await session.scalars(
            select(Share).where(Share.deck_id == deck.id).order_by(Share.created_at.desc())
        )
    ).all()
    return [_view(row) for row in rows]


@router.post("/{share_id}/revoke", response_model=ShareView)
async def revoke_share(
    share_id: UUID, user: CurrentUser, session: SessionDep, request: Request
) -> ShareView:
    share = await _owned_share(session, share_id, user.id)
    await share_service.revoke(session, share, user.id)
    await audit(
        session,
        action="share.revoke",
        user_id=user.id,
        target_type="share",
        target_id=str(share.id),
        request=request,
    )
    return _view(share)


@router.get("/guest/{slug}", response_model=GuestInfo)
async def guest_info(slug: str, session: SessionDep) -> GuestInfo:
    share = await share_service.active_share(session, slug)
    deck = await share_service.share_deck(session, share)
    return GuestInfo(
        title=deck.title,
        requires_password=True,
        expires_at=share.expires_at,
    )


@router.post("/guest/{slug}/unlock", response_model=UnlockResponse)
async def guest_unlock(
    slug: str,
    payload: UnlockRequest,
    session: SessionDep,
    request: Request,
    response: Response,
) -> UnlockResponse:
    share = await share_service.active_share(session, slug)
    deck = await share_service.share_deck(session, share)
    raw_token, expires = await share_service.unlock(session, share, payload.password, request)
    response.set_cookie(
        key=share_service.share_cookie_name(slug),
        value=raw_token,
        expires=expires,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    deck_payload = await load_deck_at(session, deck.id, deck.current_version_seq)
    parsed = Deck.model_validate(deck_payload)
    return UnlockResponse(
        deck=parsed.model_dump(mode="json", by_alias=True),
        version_seq=deck.current_version_seq,
        allow_download=share.allow_download,
        download_formats=list(share.download_formats or []),
        degraded_slides=[slide.id for slide in parsed.slides if slide.degraded],
    )


@router.post("/guest/{slug}/downloads/{fmt}", response_model=GuestDownload)
async def guest_download(
    slug: str,
    fmt: str,
    session: SessionDep,
    request: Request,
    response: Response,
) -> GuestDownload:
    share = await share_service.active_share(session, slug)
    raw_token, token_expires = await share_service.require_unlocked(session, share, request)
    response.set_cookie(
        key=share_service.share_cookie_name(slug),
        value=raw_token,
        expires=token_expires,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    share_service.ensure_format_allowed(share, fmt)
    deck = await share_service.share_deck(session, share)
    async with share_service.download_lock(share.id, fmt):
        artifact, _ = await create_export(
            session,
            deck_row=deck,
            user_id=share.created_by,
            fmt=fmt,
        )
    await share_service.log_access(
        session, share, f"download_{fmt}", request, {"artifactId": str(artifact.id)}
    )
    if settings.storage_backend == "s3":
        url = await storage.url_for(artifact.storage_key, settings.download_url_ttl_s)
        expires = datetime.now(UTC) + timedelta(seconds=settings.download_url_ttl_s)
    else:
        url = f"/api/shares/guest/{slug}/files/{artifact.id}"
        expires = None
    return GuestDownload(
        url=url,
        degraded=artifact.degraded,
        degraded_notes=list(artifact.degraded_notes or []),
        degraded_details=list(artifact.degraded_details or []),
        expires_at=expires,
    )


@router.get("/guest/{slug}/files/{artifact_id}")
async def guest_file(
    slug: str,
    artifact_id: UUID,
    session: SessionDep,
    request: Request,
    response: Response,
) -> Response:
    share = await share_service.active_share(session, slug)
    raw_token, token_expires = await share_service.require_unlocked(session, share, request)
    if not share.allow_download:
        raise ConflictError("该分享不允许下载")
    artifact = await session.get(ExportArtifact, artifact_id)
    if artifact is None or artifact.deck_id != share.deck_id:
        raise NotFoundError("导出物不存在")
    share_service.ensure_format_allowed(share, artifact.format)
    data = await storage.get_bytes(artifact.storage_key)
    result = Response(
        content=data,
        media_type={
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "gif": "image/gif",
            "html": "text/html; charset=utf-8",
        }.get(artifact.format, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{share.slug}.{artifact.format}"'},
    )
    result.set_cookie(
        key=share_service.share_cookie_name(slug),
        value=raw_token,
        expires=token_expires,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return result
