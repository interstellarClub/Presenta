import mimetypes
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocAsset, Document
from app.services.ingest.docx import _IMAGE_SUFFIX, DocxResult
from app.services.storage import sha256_bytes, storage


def _suffix_for(mime: str, name: str) -> str:
    if mime in _IMAGE_SUFFIX:
        return _IMAGE_SUFFIX[mime]
    guessed = mimetypes.guess_extension(mime or "")
    if guessed:
        return guessed.lstrip(".")
    tail = name.rsplit(".", 1)
    return tail[1].lower()[:8] if len(tail) == 2 else "bin"


async def _existing_asset(session: AsyncSession, document_id: UUID, sha256: str) -> DocAsset | None:
    return await session.scalar(
        select(DocAsset).where(DocAsset.document_id == document_id, DocAsset.sha256 == sha256)
    )


async def store_image(
    session: AsyncSession,
    *,
    document_id: UUID,
    asset_id: str,
    blob: bytes,
    mime: str,
    name: str,
    source_ref: dict[str, Any],
) -> DocAsset:
    digest = sha256_bytes(blob)
    existing = await _existing_asset(session, document_id, digest)
    if existing is not None:
        existing.ref_count = int(existing.ref_count or 0) + 1
        if existing.storage_key and not existing.storage_key.endswith(asset_id):
            stored = await storage.put_bytes(
                f"documents/{document_id}/assets/{asset_id}.{_suffix_for(mime, name)}",
                blob,
                mime,
            )
            aliases = dict((existing.meta or {}).get("aliases") or {})
            aliases[asset_id] = stored
            existing.meta = {**(existing.meta or {}), "aliases": aliases}
        await session.flush()
        return existing

    key = f"documents/{document_id}/assets/{asset_id}.{_suffix_for(mime, name)}"
    await storage.put_bytes(key, blob, mime)
    asset = DocAsset(
        id=UUID(hex=asset_id),
        document_id=document_id,
        kind="image",
        sha256=digest,
        storage_key=key,
        mime=mime,
        size_bytes=len(blob),
        source_ref=source_ref,
        meta={"name": name},
        ref_count=1,
    )
    session.add(asset)
    await session.flush()
    return asset


async def store_table(
    session: AsyncSession,
    *,
    document_id: UUID,
    asset_id: str,
    columns: list[str],
    rows: list[list[str]],
    source_ref: dict[str, Any],
    csv_text: str = "",
) -> DocAsset:
    payload = {"columns": columns, "rows": rows}
    digest = sha256_bytes((csv_text or repr(payload)).encode("utf-8"))
    existing = await _existing_asset(session, document_id, digest)
    if existing is not None:
        existing.ref_count = int(existing.ref_count or 0) + 1
        await session.flush()
        return existing
    key = f"documents/{document_id}/assets/{asset_id}.csv"
    if csv_text:
        await storage.put_bytes(key, csv_text.encode("utf-8"), "text/csv")
    asset = DocAsset(
        id=UUID(hex=asset_id),
        document_id=document_id,
        kind="table",
        sha256=digest,
        storage_key=key,
        mime="text/csv",
        size_bytes=len(csv_text.encode("utf-8")),
        source_ref=source_ref,
        meta=payload,
        ref_count=1,
    )
    session.add(asset)
    await session.flush()
    return asset


async def store_formula(
    session: AsyncSession,
    *,
    document_id: UUID,
    asset_id: str,
    latex: str | None,
    original_xml: str,
    source_ref: dict[str, Any],
) -> DocAsset:
    digest = sha256_bytes((latex or original_xml).encode("utf-8"))
    existing = await _existing_asset(session, document_id, digest)
    if existing is not None:
        existing.ref_count = int(existing.ref_count or 0) + 1
        await session.flush()
        return existing
    asset = DocAsset(
        id=UUID(hex=asset_id),
        document_id=document_id,
        kind="formula",
        sha256=digest,
        storage_key=None,
        mime="text/x-latex",
        size_bytes=len((latex or "").encode("utf-8")),
        source_ref=source_ref,
        meta={"latex": latex, "originalXml": original_xml},
        ref_count=1,
    )
    session.add(asset)
    await session.flush()
    return asset


async def persist_docx_assets(session: AsyncSession, document: Document, result: DocxResult) -> None:
    for image in result.images:
        await store_image(
            session,
            document_id=document.id,
            asset_id=image.asset_id,
            blob=image.blob,
            mime=image.mime,
            name=image.name,
            source_ref=image.source_ref,
        )
    for table in result.tables:
        await store_table(
            session,
            document_id=document.id,
            asset_id=table.asset_id,
            columns=table.columns,
            rows=table.rows,
            source_ref=table.source_ref,
            csv_text=table.csv_text,
        )
    for formula in result.formulas:
        await store_formula(
            session,
            document_id=document.id,
            asset_id=formula.asset_id,
            latex=formula.latex,
            original_xml=formula.original_xml,
            source_ref=formula.source_ref,
        )


async def asset_ref_map(session: AsyncSession, document_id: UUID) -> dict[str, DocAsset]:
    assets = (
        await session.scalars(select(DocAsset).where(DocAsset.document_id == document_id))
    ).all()
    return {asset.id.hex: asset for asset in assets}