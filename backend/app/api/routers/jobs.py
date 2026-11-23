import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.jobs import JobView
from app.core.deps import CurrentUser, SessionDep, ensure_owner
from app.core.errors import NotFoundError
from app.db.models import Job
from app.services.jobs import request_cancel

router = APIRouter(prefix="/jobs", tags=["jobs"])

TERMINAL = {"succeeded", "failed", "cancelled", "partial"}


async def _owned_job(session: SessionDep, job_id: UUID, user_id: UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFoundError("任务不存在")
    ensure_owner(job.user_id, user_id)
    return job


def _view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{job_id}", response_model=JobView)
async def get_job(job_id: UUID, user: CurrentUser, session: SessionDep) -> JobView:
    job = await _owned_job(session, job_id, user.id)
    return _view(job)


@router.post("/{job_id}/cancel", response_model=JobView)
async def cancel_job(job_id: UUID, user: CurrentUser, session: SessionDep) -> JobView:
    job = await _owned_job(session, job_id, user.id)
    await request_cancel(session, job)
    return _view(job)


@router.get("/{job_id}/events")
async def job_events(job_id: UUID, user: CurrentUser) -> EventSourceResponse:
    from app.db.session import SessionFactory

    async def event_source() -> Any:
        seen: tuple[int, str, str | None] = (-1, "", None)
        for _ in range(1800):
            async with SessionFactory() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    yield {"event": "error", "data": json.dumps({"message": "任务不存在"})}
                    return
                if job.user_id != user.id:
                    yield {"event": "error", "data": json.dumps({"message": "无权访问"})}
                    return
                view = _view(job)
                fingerprint = (job.progress, job.status, job.stage)
                if fingerprint != seen:
                    seen = fingerprint
                    yield {
                        "event": "progress",
                        "data": json.dumps(
                            view.model_dump(mode="json", by_alias=True), ensure_ascii=False
                        ),
                    }
                terminal = job.status in TERMINAL
            if terminal:
                yield {"event": "done", "data": json.dumps({"status": view.status})}
                return
            await asyncio.sleep(1)

    return EventSourceResponse(event_source(), ping=15)