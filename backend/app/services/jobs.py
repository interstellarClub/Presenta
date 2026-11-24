import asyncio
import logging
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, UpstreamError
from app.db.models import Job, User

logger = logging.getLogger("presenta.jobs")

_LOCAL_TASKS: set[asyncio.Task[Any]] = set()
_LOCAL_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
_JOB_CREATE_LOCK = asyncio.Lock()

ARQ_FUNCTION_BY_KIND = {
    "batch_generate": "run_generate_job",
    "ingest": "run_ingest_job",
    "pdf_export": "run_export_job",
    "ppt_export": "run_export_job",
    "gif_export": "run_export_job",
    "cleanup": "run_cleanup_job",
}


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


def _active_generate_count_query(user_id: UUID) -> Any:
    return select(func.count(Job.id)).where(
        Job.user_id == user_id,
        Job.kind == "batch_generate",
        Job.status.in_(["queued", "running"]),
    )


async def create_job(
    session: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    async with _JOB_CREATE_LOCK:
        # Serialize job creation per user. PostgreSQL row locking covers multiple API instances;
        # SQLite/local uses the process lock above.
        await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
        if idempotency_key:
            existing = await session.scalar(
                select(Job).where(Job.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if existing.status in {"failed", "cancelled"}:
                    existing.status = "queued"
                    existing.progress = 0
                    existing.stage = None
                    existing.attempts = 0
                    existing.error = None
                    existing.result = None
                    existing.cancel_requested = False
                    await session.commit()
                return existing

        active = await session.scalar(
            select(Job).where(Job.user_id == user_id, Job.status.in_(["queued", "running"]))
        )
        if active is not None and kind == "batch_generate":
            active_count = int(
                await session.scalar(_active_generate_count_query(user_id)) or 0
            )
            if active_count >= settings.batch_concurrency_per_user:
                raise ConflictError(
                    f"同一用户最多同时进行 "
                    f"{settings.batch_concurrency_per_user} 个生成任务，请等待完成或取消",
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
        await session.commit()
        await session.refresh(job)
        return job


async def enqueue_job(job_id: UUID, *, kind: str | None = None) -> None:
    if settings.queue_backend == "arq":
        if kind is None:
            from app.db.models import Job as JobRow
            from app.db.session import SessionFactory

            async with SessionFactory() as session:
                job = await session.get(JobRow, job_id)
                kind = job.kind if job is not None else "batch_generate"
        function = ARQ_FUNCTION_BY_KIND.get(kind, "run_job")
        redis = Redis.from_url(settings.redis_url)
        try:
            await redis.enqueue_job(function, str(job_id))
        except Exception as exc:
            logger.error("arq enqueue failed for job %s (%s): %s", job_id, function, exc)
            raise UpstreamError("任务队列不可用，任务已保留为排队状态，请稍后重试") from exc
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
