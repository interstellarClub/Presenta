import uuid
from typing import Any, cast

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Function

from app.core.config import settings
from app.db.session import SessionFactory
from app.workers.reclaim import reclaim_stale_jobs
from app.workers.runner import run_job


async def run_generate_job(_ctx: dict[str, Any], job_id: str) -> None:
    await run_job(uuid.UUID(job_id))


async def run_ingest_job(_ctx: dict[str, Any], job_id: str) -> None:
    await run_job(uuid.UUID(job_id))


async def run_export_job(_ctx: dict[str, Any], job_id: str) -> None:
    await run_job(uuid.UUID(job_id))


async def run_cleanup_job(_ctx: dict[str, Any], job_id: str) -> None:
    await run_job(uuid.UUID(job_id))


async def patrol(_ctx: dict[str, Any]) -> int:
    async with SessionFactory() as session:
        reclaimed = await reclaim_stale_jobs(session)
        await session.commit()
        return len(reclaimed)


def _func(name: str, coro: Any, timeout_s: float) -> Function:
    return Function(
        name=name,
        coroutine=coro,
        timeout_s=timeout_s,
        keep_result_s=None,
        keep_result_forever=None,
        max_tries=1,
    )


class WorkerSettings:
    functions = [
        _func("run_generate_job", run_generate_job, settings.generate_timeout_s + 30),
        _func("run_ingest_job", run_ingest_job, settings.ingest_timeout_s + 30),
        _func("run_export_job", run_export_job, settings.export_timeout_s + 30),
        _func("run_cleanup_job", run_cleanup_job, settings.cleanup_timeout_s + 30),
        _func("run_job", run_generate_job, settings.generate_timeout_s + 30),
    ]
    cron_jobs = [cron(cast(Any, patrol), minute=set(range(60)), run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = settings.generate_timeout_s + 30
    keep_result = 3600