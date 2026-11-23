from datetime import UTC
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import token_digest
from app.db.models import Session as SessionRow
from app.db.models import User
from app.db.session import get_session


def session_token(request: Request) -> str | None:
    return request.cookies.get(settings.session_cookie)


async def optional_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User | None:
    token = session_token(request)
    if not token:
        return None
    row = await session.scalar(
        select(SessionRow).where(SessionRow.token_hash == token_digest(token))
    )
    if row is None or row.revoked_at is not None:
        return None
    from datetime import datetime

    if row.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return None
    user = await session.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    request.state.user = user
    request.state.session_row = row
    return user


async def current_user(
    user: Annotated[User | None, Depends(optional_user)],
) -> User:
    if user is None:
        raise UnauthorizedError("请先登录")
    return user


def ensure_owner(owner_id: object, user_id: object) -> None:
    if owner_id != user_id:
        raise ForbiddenError("无权访问该资源")


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]