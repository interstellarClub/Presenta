import asyncio
import logging
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError
from app.db.models import Job

logger = logging.getLogger("presenta.jobs")

_LOCAL_TASKS: set[asyncio.Task[Any]] = set()
_LOCAL_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _local_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _LOCAL_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _LOCAL_LOCKS[loop] = lock
    return lock


async def _run_local_serialized(job_id: UUID) -> None:
    from app.workers.runner import run_job

    await asyncio.sleep(0.05)
    async with _local_lock():
        await run_job(job_id)


async def create_job(
    session: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    if idempotency_key:
        existing = await session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
    active = await session.scalar(
        select(Job).where(
            Job.user_id == user_id,
            Job.kind == kind,
            Job.status.in_(["queued", "running"]),
        )
    )
    if active is not None and kind == "batch_generate":
        raise ConflictError(
            "已有生成任务在进行中，请等待完成或取消",
            details={"jobId": str(active.id)},
        )
    job = Job(
        user_id=user_id,
        kind=kind,
        payload=payload,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.flush()
    return job


async def enqueue_job(job_id: UUID) -> None:
    if settings.queue_backend == "arq":
        redis = Redis.from_url(settings.redis_url)
        try:
            await redis.enqueue_job("run_job", str(job_id))
        except Exception as exc:
            logger.error("arq enqueue failed, falling back to local runner: %s", exc)
            _spawn_local(job_id)
        finally:
            await redis.aclose()
        return
    _spawn_local(job_id)


def _spawn_local(job_id: UUID) -> None:
    task = asyncio.create_task(_run_local_serialized(job_id))
    _LOCAL_TASKS.add(task)

    def _on_done(completed: asyncio.Task[Any]) -> None:
        _LOCAL_TASKS.discard(completed)
        if completed.cancelled():
            logger.warning("local job task %s was cancelled", job_id)
            return
        error = completed.exception()
        if error is not None:
            logger.error("local job task %s crashed: %r", job_id, error)

    task.add_done_callback(_on_done)


async def request_cancel(session: AsyncSession, job: Job) -> Job:
    if job.status in {"queued", "running"}:
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
        await session.flush()
    return job