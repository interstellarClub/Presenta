from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Deck as DeckRow
from app.db.models import ExportArtifact, Share, ShareAccessLog
from app.services.storage import storage

ACCESS_LOG_RETENTION_DAYS = 30
SHARE_TOMBSTONE_DAYS = 7


async def run_cleanup(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    counts = {
        "artifacts": 0,
        "decks": 0,
        "shares": 0,
        "accessLogs": 0,
        "storageErrors": 0,
    }

    expired_artifacts = (
        await session.scalars(
            select(ExportArtifact).where(ExportArtifact.expires_at < now)
        )
    ).all()
    for artifact in expired_artifacts:
        try:
            await storage.delete(artifact.storage_key)
        except Exception:
            counts["storageErrors"] += 1
        await session.delete(artifact)
        counts["artifacts"] += 1

    cutoff = now - timedelta(days=settings.purge_retention_days)
    deleted_decks = (
        await session.scalars(
            select(DeckRow).where(DeckRow.deleted_at.is_not(None), DeckRow.deleted_at < cutoff)
        )
    ).all()
    for deck in deleted_decks:
        artifacts = (
            await session.scalars(
                select(ExportArtifact).where(ExportArtifact.deck_id == deck.id)
            )
        ).all()
        for artifact in artifacts:
            try:
                await storage.delete(artifact.storage_key)
            except Exception:
                counts["storageErrors"] += 1
            await session.delete(artifact)
        await session.delete(deck)
        counts["decks"] += 1

    share_cutoff = now - timedelta(days=SHARE_TOMBSTONE_DAYS)
    expired_shares = (
        await session.scalars(
            select(Share).where(
                or_(Share.expires_at < share_cutoff, Share.revoked_at < share_cutoff)
            )
        )
    ).all()
    for share in expired_shares:
        await session.delete(share)
        counts["shares"] += 1

    log_cutoff = now - timedelta(days=ACCESS_LOG_RETENTION_DAYS)
    result = await session.execute(
        delete(ShareAccessLog).where(ShareAccessLog.created_at < log_cutoff)
    )
    counts["accessLogs"] = int(getattr(result, "rowcount", 0) or 0)

    await session.flush()
    return counts