from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserProfile
from app.core.audit import audit
from app.core.config import settings
from app.core.deps import CurrentUser, OptionalUser, SessionDep
from app.core.errors import ForbiddenError, RateLimitError, UnauthorizedError, ValidationFailedError
from app.core.ratelimit import limiter
from app.core.security import (
    hash_password,
    invite_code_hash,
    new_opaque_token,
    normalize_email,
    token_digest,
    verify_password,
)
from app.db.models import InviteCode, InviteRedemption, User
from app.db.models import Session as SessionRow

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        created_at=user.created_at,
    )


def _set_cookie(response: Response, token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


async def _issue_session(session: SessionDep, user: User, request: Request) -> tuple[str, datetime]:
    raw = new_opaque_token(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    row = SessionRow(
        user_id=user.id,
        token_hash=token_digest(raw),
        expires_at=expires_at,
        ip_hash=None,
        user_agent_hash=None,
    )
    session.add(row)
    await session.flush()
    return raw, expires_at


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> AuthResponse:
    ip = _client_ip(request)
    allowed = await limiter.allow(
        f"register:{ip}", settings.rate_limit_register_per_hour, settings.rate_limit_window_s
    )
    if not allowed:
        raise RateLimitError("注册尝试过于频繁，请稍后再试")

    code_hash = invite_code_hash(payload.invite_code)
    invite = await session.scalar(select(InviteCode).where(InviteCode.code_hash == code_hash))
    now = datetime.now(UTC)
    if invite is None:
        raise ValidationFailedError("邀请码无效")
    if invite.revoked_at is not None:
        raise ValidationFailedError("邀请码已被吊销")
    if invite.expires_at is not None and invite.expires_at.replace(tzinfo=UTC) < now:
        raise ValidationFailedError("邀请码已过期")
    if invite.used_count >= invite.max_uses:
        raise ValidationFailedError("邀请码已用尽")

    email = normalize_email(payload.email)
    exists = await session.scalar(select(User).where(User.email == email))
    if exists is not None:
        raise ValidationFailedError("该邮箱已注册")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        status="active",
        last_login_at=now,
    )
    session.add(user)
    await session.flush()

    invite.used_count += 1
    session.add(InviteRedemption(code_id=invite.id, user_id=user.id))
    await audit(
        session,
        action="auth.register",
        user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        request=request,
        meta={"inviteCodeId": str(invite.id)},
    )

    raw, expires_at = await _issue_session(session, user, request)
    _set_cookie(response, raw, expires_at)
    return AuthResponse(user=_profile(user), expires_at=expires_at)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> AuthResponse:
    ip = _client_ip(request)
    email = normalize_email(payload.email)
    allowed = await limiter.allow(
        f"login:{ip}:{email}", settings.rate_limit_login_per_hour, settings.rate_limit_window_s
    )
    if not allowed:
        raise RateLimitError("登录尝试过于频繁，请稍后再试")

    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        await audit(
            session,
            action="auth.login_failed",
            request=request,
            meta={"email": email},
        )
        raise UnauthorizedError("邮箱或密码不正确")
    if user.status != "active":
        raise ForbiddenError("账号不可用，请联系管理员")

    user.last_login_at = datetime.now(UTC)
    raw, expires_at = await _issue_session(session, user, request)
    await audit(
        session,
        action="auth.login",
        user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        request=request,
    )
    _set_cookie(response, raw, expires_at)
    return AuthResponse(user=_profile(user), expires_at=expires_at)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: SessionDep) -> Response:
    row = getattr(request.state, "session_row", None)
    if row is not None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    response.delete_cookie(settings.session_cookie, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=AuthResponse)
async def me(user: CurrentUser, session: SessionDep, request: Request) -> AuthResponse:
    row = getattr(request.state, "session_row", None)
    expires_at = row.expires_at if row is not None else datetime.now(UTC)
    return AuthResponse(user=_profile(user), expires_at=expires_at)


@router.get("/optional", response_model=UserProfile | None)
async def optional_profile(user: OptionalUser) -> UserProfile | None:
    return _profile(user) if user is not None else None