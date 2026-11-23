from typing import Any, cast

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.db.session import SessionFactory
from app.workers.reclaim import reclaim_stale_jobs
from app.workers.runner import run_job


async def run_job_task(_ctx: dict[str, Any], job_id: str) -> None:
    import uuid

    await run_job(uuid.UUID(job_id))


async def patrol(_ctx: dict[str, Any]) -> int:
    async with SessionFactory() as session:
        reclaimed = await reclaim_stale_jobs(session)
        await session.commit()
        return len(reclaimed)


class WorkerSettings:
    functions = [run_job_task]
    cron_jobs = [cron(cast(Any, patrol), minute={0, 15, 30, 45}, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 1800
    keep_result = 3600