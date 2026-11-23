import asyncio
import logging
import socket
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.api.schemas.outline import Outline
from app.core.config import settings
from app.db.models import Deck, Document, Job
from app.db.session import SessionFactory
from app.services.export.service import create_export
from app.services.ingest.normalize import IngestError, ingest_document
from app.services.pages.generator import JobCancelled, generate_pages

logger = logging.getLogger("presenta.worker")

HEARTBEAT_INTERVAL_S = 15


async def _heartbeat(job_id: UUID, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_S)
            return
        except TimeoutError:
            pass
        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.heartbeat_at = datetime.now(UTC)
            await session.commit()


def _session_progress(session, job_row: Job):
    async def write(percent: int, stage: str) -> None:
        job_row.progress = max(0, min(100, percent))
        job_row.stage = stage[:64]
        job_row.heartbeat_at = datetime.now(UTC)
        await session.flush()
        await session.commit()

    return write


def _cancel_checker(job_id: UUID):
    async def check() -> bool:
        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            return bool(job and job.cancel_requested)

    return check


async def run_job(job_id: UUID) -> None:
    stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    if not settings.uses_sqlite:
        heartbeat_task = asyncio.create_task(_heartbeat(job_id, stop))
    try:
        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status not in {"queued", "running"}:
                return
            if job.cancel_requested:
                job.status = "cancelled"
                await session.commit()
                return
            job.status = "running"
            job.attempts += 1
            job.locked_by = socket.gethostname()[:120]
            job.locked_at = datetime.now(UTC)
            job.heartbeat_at = datetime.now(UTC)
            job.error = None
            await session.commit()
            user_id = job.user_id
            payload = dict(job.payload)
            kind = job.kind
            deck_id = payload.get("deckId")


        check_cancel = _cancel_checker(job_id)
        result: dict[str, Any] = {}
        final_status = "succeeded"

        async with SessionFactory() as session:
            job_row = await session.get(Job, job_id)
            if job_row is None:
                return
            progress = _session_progress(session, job_row)
            if kind == "ingest":
                document = await session.get(Document, UUID(str(payload["documentId"])))
                if document is None:
                    raise IngestError("document not found")
                try:
                    result = await ingest_document(
                        session,
                        document,
                        progress=progress,
                        check_cancel=check_cancel,
                    )
                except IngestError as exc:
                    document.status = "failed"
                    document.error = {"code": "ingest_failed", "message": exc.message}
                    await session.commit()
                    raise
                await session.commit()
            elif kind == "batch_generate":
                deck_row = await session.get(Deck, UUID(str(deck_id)))
                if deck_row is None or deck_row.document_id is None:
                    raise IngestError("deck or document not found")
                document = await session.get(Document, deck_row.document_id)
                if document is None:
                    raise IngestError("document not found")
                outline = Outline.model_validate(payload["outline"])
                deck, versions = await generate_pages(
                    session,
                    deck_row=deck_row,
                    document=document,
                    outline=outline,
                    user_id=user_id,
                    job_id=job_id,
                    progress=progress,
                    check_cancel=check_cancel,
                )
                degraded = [slide.id for slide in deck.slides if slide.degraded]
                result = {
                    "deckId": str(deck_row.id),
                    "slides": len(deck.slides),
                    "degradedSlides": degraded,
                    "versionSeq": versions[-1].seq if versions else deck_row.current_version_seq,
                }
                if degraded:
                    final_status = "partial"
                await session.commit()
            elif kind in {"pdf_export", "gif_export", "ppt_export"}:
                deck_row = await session.get(Deck, UUID(str(payload["deckId"])))
                if deck_row is None:
                    raise IngestError("deck not found for export")
                fmt = {"pdf_export": "pdf", "gif_export": "gif", "ppt_export": "pptx"}[kind]
                job_row.progress = 15
                job_row.stage = "warming"
                await session.commit()
                artifact, cached = await create_export(
                    session,
                    deck_row=deck_row,
                    user_id=user_id,
                    fmt=fmt,
                    options=dict(payload.get("options") or {}),
                    version_seq=int(payload["versionSeq"])
                    if payload.get("versionSeq")
                    else None,
                )
                result = {
                    "artifactId": str(artifact.id),
                    "format": fmt,
                    "bytes": artifact.bytes,
                    "degraded": artifact.degraded,
                    "notes": list(artifact.degraded_notes or []),
                    "cached": cached,
                }
                if artifact.degraded:
                    final_status = "partial"
                await session.commit()
            elif kind == "cleanup":
                from app.services.cleanup import run_cleanup

                result = await run_cleanup(session)
                await session.commit()
            else:
                raise IngestError(f"unsupported job kind '{kind}'")

        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            if job.cancel_requested:
                job.status = "cancelled"
            else:
                job.status = final_status
                job.result = result
                job.progress = 100
                job.stage = "done"
            await session.commit()
    except JobCancelled:
        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = "cancelled"
                job.stage = "cancelled"
                await session.commit()
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        async with SessionFactory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.error = {"code": type(exc).__name__, "message": str(exc)[:1000]}
            if job.attempts < job.max_attempts:
                job.status = "queued"
                job.locked_by = None
                job.locked_at = None
                await session.commit()
                from app.services.jobs import enqueue_job

                await enqueue_job(job_id)
                return
            job.status = "failed"
            await session.commit()
    finally:
        stop.set()
        if heartbeat_task is not None:
            with suppress(Exception):
                await asyncio.wait_for(heartbeat_task, timeout=5)