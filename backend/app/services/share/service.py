import asyncio
import contextlib
import hashlib
import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_isolated
from app.core.config import settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.ratelimit import limiter
from app.core.security import (
    hash_password,
    mask_ip,
    new_opaque_token,
    new_share_slug,
    token_digest,
    verify_password,
)
from app.db.models import Deck as DeckRow
from app.db.models import Share, ShareAccessLog, ShareToken

logger = logging.getLogger("presenta.share")
SHARE_PASSWORD_ATTEMPTS = 8
ALLOWED_FORMATS = {"pdf", "pptx", "html", "gif", "mp4"}
_PASSWORD_HAS_LETTER = re.compile(r"[A-Za-z]")
_PASSWORD_HAS_DIGIT = re.compile(r"\d")
_DOWNLOAD_LOCKS: dict[tuple[int, str, str], asyncio.Lock] = {}
_LOCK_TTL_S = 300


def share_cookie_name(slug: str) -> str:
    return f"presenta_share_{slug}"


@contextlib.asynccontextmanager
async def download_lock(share_id: UUID, fmt: str) -> AsyncIterator[None]:
    lock_key = f"presenta:share:lock:{share_id}:{fmt}"
    if settings.queue_backend == "arq":
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        token = hashlib.sha256(f"{share_id}:{fmt}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()
        acquired = False
        try:
            acquired = await redis.set(lock_key, token, nx=True, ex=_LOCK_TTL_S)
            if not acquired:
                raise ConflictError("该分享正在生成导出物，请稍后重试")
            yield
        finally:
            if acquired:
                try:
                    existing = await redis.get(lock_key)
                    if existing and existing.decode() == token:
                        await redis.delete(lock_key)
                except Exception:
                    logger.warning("failed to release share lock %s", lock_key)
            await redis.aclose()
        return

    loop = asyncio.get_running_loop()
    key = (id(loop), str(share_id), fmt)
    lock = _DOWNLOAD_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _DOWNLOAD_LOCKS[key] = lock
    async with lock:
        yield


def validate_share_password(password: str) -> None:
    if len(password) < 8:
        raise ValidationFailedError("分享密码至少 8 位")
    if not _PASSWORD_HAS_LETTER.search(password) or not _PASSWORD_HAS_DIGIT.search(password):
        raise ValidationFailedError("分享密码需同时包含字母与数字")


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
    validate_share_password(password)
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


def _attempt_key(share: Share, request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"share:{share.slug}:{mask_ip(ip) or ip}"


async def _log_access_isolated(
    share: Share, kind: str, request: Request, meta: dict | None = None
) -> None:
    from app.db.session import SessionFactory

    try:
        async with SessionFactory() as session:
            await log_access(session, share, kind, request, meta)
            await session.commit()
    except Exception:
        import logging

        logging.getLogger("presenta.share").exception(
            "isolated share access log failed for kind=%s", kind
        )


async def unlock(
    session: AsyncSession, share: Share, password: str, request: Request
) -> tuple[str, datetime]:
    allowed = await limiter.allow(
        _attempt_key(share, request), SHARE_PASSWORD_ATTEMPTS, settings.rate_limit_window_s
    )
    if not allowed:
        await _log_access_isolated(share, "auth_fail", request, {"reason": "locked"})
        await audit_isolated(
            action="share.auth_locked",
            target_type="share",
            target_id=str(share.id),
            request=request,
        )
        raise RateLimitError("分享密码尝试过于频繁，请稍后再试")

    if not verify_password(password or "", share.password_hash):
        await _log_access_isolated(share, "auth_fail", request, {"reason": "bad_password"})
        await audit_isolated(
            action="share.auth_fail",
            target_type="share",
            target_id=str(share.id),
            request=request,
        )
        raise UnauthorizedError("访问密码不正确")

    raw = new_opaque_token(32)
    expires = min(
        datetime.now(UTC) + timedelta(seconds=settings.share_session_ttl_s),
        share.expires_at.replace(tzinfo=UTC),
    )
    session.add(
        ShareToken(
            share_id=share.id,
            token_hash=token_digest(raw),
            expires_at=expires,
            ip_hash=mask_ip(request.client.host) if request.client else None,
        )
    )
    share.view_count += 1
    await log_access(session, share, "view", request)
    await session.flush()
    return raw, expires


async def require_unlocked(
    session: AsyncSession, share: Share, request: Request
) -> tuple[str, datetime]:
    raw = request.cookies.get(share_cookie_name(share.slug))
    if not raw:
        raise UnauthorizedError("请先输入访问密码")
    token = await session.scalar(
        select(ShareToken).where(
            ShareToken.token_hash == token_digest(raw), ShareToken.share_id == share.id
        )
    )
    if token is None or token.revoked_at is not None:
        raise UnauthorizedError("访问凭证无效，请重新输入密码")
    now = datetime.now(UTC)
    expires_at = token.expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise UnauthorizedError("访问凭证已过期，请重新输入密码")
    token.last_used_at = now
    remaining = (expires_at - now).total_seconds()
    if remaining < settings.share_session_ttl_s / 2:
        renewed = min(
            now + timedelta(seconds=settings.share_session_ttl_s),
            share.expires_at.replace(tzinfo=UTC),
        )
        if renewed > expires_at:
            token.expires_at = renewed
    await session.flush()
    return raw, token.expires_at.replace(tzinfo=UTC)


def ensure_format_allowed(share: Share, fmt: str) -> None:
    if not share.allow_download:
        raise ConflictError("该分享不允许下载")
    if fmt not in (share.download_formats or []):
        raise ConflictError(f"该分享不提供 {fmt} 下载")


async def revoke(session: AsyncSession, share: Share, user_id: UUID) -> None:
    if share.created_by != user_id:
        raise ForbiddenError("无权吊销该分享")
    share.revoked_at = datetime.now(UTC)
    tokens = (
        await session.scalars(select(ShareToken).where(ShareToken.share_id == share.id))
    ).all()
    for token in tokens:
        token.revoked_at = datetime.now(UTC)
    await session.flush()
