import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Deck as DeckRow
from app.db.models import DocAsset, Document, ExportArtifact, Share, ShareAccessLog, ShareToken
from app.services.storage import storage

logger = logging.getLogger("presenta.cleanup")

ACCESS_LOG_RETENTION_DAYS = 30
SHARE_TOMBSTONE_DAYS = 7


async def _delete_object(key: str | None) -> bool:
    if not key:
        return True
    try:
        await storage.delete(key)
        return True
    except Exception as exc:
        logger.error("cleanup storage delete failed for %s: %s", key, exc)
        return False


async def run_cleanup(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    counts = {
        "artifacts": 0,
        "decks": 0,
        "shares": 0,
        "shareTokens": 0,
        "accessLogs": 0,
        "orphanAssets": 0,
        "storageErrors": 0,
        "skipped": 0,
    }

    expired_artifacts = (
        await session.scalars(select(ExportArtifact).where(ExportArtifact.expires_at < now))
    ).all()
    for artifact in expired_artifacts:
        if not await _delete_object(artifact.storage_key):
            counts["storageErrors"] += 1
            counts["skipped"] += 1
            continue
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
        failures = 0
        for artifact in artifacts:
            if not await _delete_object(artifact.storage_key):
                failures += 1
                counts["storageErrors"] += 1
            else:
                await session.delete(artifact)
        if failures:
            counts["skipped"] += 1
            logger.warning("deck %s purge deferred: %s artifact objects could not be deleted", deck.id, failures)
            continue
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

    token_cutoff = now - timedelta(days=settings.share_token_keep_expired_days)
    result = await session.execute(
        delete(ShareToken).where(ShareToken.expires_at < token_cutoff)
    )
    counts["shareTokens"] = int(getattr(result, "rowcount", 0) or 0)

    log_cutoff = now - timedelta(days=ACCESS_LOG_RETENTION_DAYS)
    result = await session.execute(
        delete(ShareAccessLog).where(ShareAccessLog.created_at < log_cutoff)
    )
    counts["accessLogs"] = int(getattr(result, "rowcount", 0) or 0)

    referenced: set[str] = set()
    for key in (await session.scalars(select(DocAsset.storage_key))).all():
        if key:
            referenced.add(key)
    for key in (await session.scalars(select(Document.original_key))).all():
        if key:
            referenced.add(key)
    for meta in (await session.scalars(select(DocAsset.meta))).all():
        if meta and isinstance(meta.get("aliases"), dict):
            for alias_key in meta["aliases"].values():
                if isinstance(alias_key, str) and alias_key:
                    referenced.add(alias_key)
    try:
        candidates = await storage.list_keys(
            "documents", older_than_s=settings.orphan_grace_days * 86400
        )
    except Exception as exc:
        logger.error("cleanup orphan scan failed: %s", exc)
        counts["storageErrors"] += 1
        candidates = []
    for key in candidates:
        if key in referenced:
            continue
        if await _delete_object(key):
            counts["orphanAssets"] += 1
        else:
            counts["storageErrors"] += 1

    if counts["storageErrors"]:
        logger.critical(
            "cleanup finished with storage failures: errors=%s skipped=%s",
            counts["storageErrors"],
            counts["skipped"],
        )

    await session.flush()
    return counts