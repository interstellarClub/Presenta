import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.security import hash_password, mask_ip, new_share_slug, verify_password
from app.db.models import Deck as DeckRow
from app.db.models import Share, ShareAccessLog

SHARE_SESSION_TTL_S = 7200
ALLOWED_FORMATS = {"pdf", "pptx", "html", "mp4", "gif"}


def share_cookie_name(slug: str) -> str:
    return f"presenta_share_{slug}"


def _sign(slug: str, expires_at: int) -> str:
    message = f"{slug}:{expires_at}".encode()
    signature = hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def issue_share_cookie(slug: str, share_expires_at: datetime) -> tuple[str, datetime]:
    hard_stop = datetime.now(UTC) + timedelta(seconds=SHARE_SESSION_TTL_S)
    expires = min(
        hard_stop,
        share_expires_at.replace(tzinfo=UTC)
        if share_expires_at.tzinfo is None
        else share_expires_at,
    )
    return _sign(slug, int(expires.timestamp())), expires


def verify_share_cookie(slug: str, raw: str | None) -> bool:
    if not raw or "." not in raw:
        return False
    stamp, signature = raw.split(".", 1)
    try:
        expires_at = int(stamp)
    except ValueError:
        return False
    if expires_at < int(datetime.now(UTC).timestamp()):
        return False
    expected = _sign(slug, expires_at)
    return hmac.compare_digest(expected.encode("utf-8"), raw.encode("utf-8"))


async def create_share(
    session: AsyncSession,
    *,
    deck: DeckRow,
    created_by: UUID,
    password: str,
    ttl_hours: int,
    allow_download: bool,
    formats: list[str] | None,
) -> Share:
    if deck.user_id != created_by:
        raise ForbiddenError("无权分享该演示文稿")
    if len(password) < 4:
        raise ValidationFailedError("分享密码至少 4 位")
    chosen = sorted(set(formats or ALLOWED_FORMATS))
    unknown = set(chosen) - ALLOWED_FORMATS
    if unknown:
        raise ValidationFailedError(f"不支持的下载格式：{sorted(unknown)}")
    share = Share(
        deck_id=deck.id,
        created_by=created_by,
        slug=new_share_slug(),
        password_hash=hash_password(password),
        expires_at=datetime.now(UTC) + timedelta(hours=max(1, ttl_hours)),
        allow_download=allow_download,
        download_formats=chosen,
    )
    session.add(share)
    await session.flush()
    return share


async def active_share(session: AsyncSession, slug: str) -> Share:
    share = await session.scalar(select(Share).where(Share.slug == slug))
    if share is None:
        raise NotFoundError("分享不存在")
    if share.revoked_at is not None:
        raise NotFoundError("分享已吊销")
    expires_at = share.expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise NotFoundError("分享已过期")
    return share


async def share_deck(session: AsyncSession, share: Share) -> DeckRow:
    deck = await session.get(DeckRow, share.deck_id)
    if deck is None or deck.deleted_at is not None:
        raise NotFoundError("演示文稿已删除，分享失效")
    return deck


async def log_access(
    session: AsyncSession,
    share: Share,
    kind: str,
    request: Request | None,
    meta: dict | None = None,
) -> None:
    ip_hash = None
    ua_hash = None
    if request is not None and request.client is not None:
        ip_hash = mask_ip(request.client.host)
        user_agent = request.headers.get("user-agent")
        if user_agent:
            ua_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:32]
    session.add(
        ShareAccessLog(
            share_id=share.id,
            kind=kind,
            ip_hash=ip_hash,
            user_agent_hash=ua_hash,
            meta=meta,
        )
    )
    await session.flush()


async def unlock(session: AsyncSession, share: Share, password: str, request: Request) -> tuple[str, datetime]:
    if not verify_password(password or "", share.password_hash):
        await log_access(session, share, "auth_fail", request)
        raise UnauthorizedError("访问密码不正确")
    token, expires = issue_share_cookie(share.slug, share.expires_at)
    share.view_count += 1
    await log_access(session, share, "view", request)
    return token, expires


def require_unlocked(slug: str, request: Request) -> None:
    if not verify_share_cookie(slug, request.cookies.get(share_cookie_name(slug))):
        raise UnauthorizedError("请先输入访问密码")


def ensure_format_allowed(share: Share, fmt: str) -> None:
    if not share.allow_download:
        raise ConflictError("该分享不允许下载")
    if fmt not in (share.download_formats or []):
        raise ConflictError(f"该分享不提供 {fmt} 下载")


async def revoke(session: AsyncSession, share: Share, user_id: UUID) -> None:
    if share.created_by != user_id:
        raise ForbiddenError("无权吊销该分享")
    share.revoked_at = datetime.now(UTC)
    await session.flush()