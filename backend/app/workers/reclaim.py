from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.workers.runner import run_job

STALE_AFTER_S = 90


def _stale_clause(cutoff: datetime):
    return (
        Job.status == "running",
        or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < cutoff),
    )


async def reclaim_stale_jobs(session: AsyncSession) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(seconds=STALE_AFTER_S)
    stale = (await session.scalars(select(Job).where(*_stale_clause(cutoff)))).all()
    reclaimed: list[str] = []
    for job in stale:
        job.locked_by = None
        job.locked_at = None
        if job.attempts < job.max_attempts:
            job.status = "queued"
            reclaimed.append(str(job.id))
        else:
            job.status = "failed"
            job.error = {
                "code": "worker_lost",
                "message": "worker heartbeat expired and retries exhausted",
            }
    await session.flush()
    await session.commit()

    from app.services.jobs import enqueue_job

    for job in stale:
        if str(job.id) in reclaimed:
            await enqueue_job(job.id, kind=job.kind)
    return reclaimed


async def heartbeat_stale_check(session: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=STALE_AFTER_S)
    rows = (await session.scalars(select(Job).where(*_stale_clause(cutoff)))).all()
    return len(rows)


__all__ = ["reclaim_stale_jobs", "heartbeat_stale_check", "run_job"]