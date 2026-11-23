from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import mask_ip
from app.db.models import AuditLog


async def audit(
    session: AsyncSession,
    *,
    action: str,
    user_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request: Request | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    ip_hash = None
    if request is not None and request.client is not None:
        ip_hash = mask_ip(request.client.host)
    session.add(
        AuditLog(
            user_id=user_id,
            action=action[:48],
            target_type=target_type[:32] if target_type else None,
            target_id=str(target_id)[:64] if target_id else None,
            ip_hash=ip_hash,
            meta=meta,
        )
    )
    await session.flush()