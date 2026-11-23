from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageLedger


async def record_usage(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    purpose: str,
    thinking: bool,
    latency_ms: int,
    success: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    user_id: UUID | None = None,
    deck_id: UUID | None = None,
    job_id: UUID | None = None,
    error_code: str | None = None,
    now: datetime | None = None,
) -> None:
    entry = UsageLedger(
        provider=provider,
        model=model,
        purpose=purpose,
        thinking=thinking,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms,
        success=success,
        error_code=error_code,
        user_id=user_id,
        deck_id=deck_id,
        job_id=job_id,
        created_at=now or datetime.now(UTC),
    )
    session.add(entry)
    await session.flush()