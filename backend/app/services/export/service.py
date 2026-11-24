import base64
import mimetypes
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Deck, schema_hash
from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.models import Deck as DeckRow
from app.db.models import DocAsset, Document, ExportArtifact
from app.services.deck.semantics import ensure_deck_semantics
from app.services.deck.versioning import load_deck_at
from app.services.export.html import build_standalone_html, theme_css
from app.services.export.layouts_html import render_slide_html
from app.services.export.pptx import build_pptx
from app.services.export.render_svc import render_pdf, render_png, render_png_sequence
from app.services.storage import safe_key, storage
from app.services.theme.manifest import load_manifest, relative_luminance, validate_manifest

FORMATS = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "gif": "image/gif",
    "mp4": "video/mp4",
}
SUFFIXES = {"html": "html", "pdf": "pdf", "pptx": "pptx", "gif": "gif", "mp4": "mp4"}


async def _image_map(
    session: AsyncSession, deck: Deck, document_id: UUID | None
) -> dict[str, str]:
    asset_ids: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("kind") == "image" and value.get("assetId"):
                asset_ids.add(str(value["assetId"]))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for slide in deck.slides:
        walk(slide.slots)
    if not asset_ids:
        return {}
    parsed: list[UUID] = []
    for asset_id in asset_ids:
        try:
            parsed.append(UUID(asset_id))
        except ValueError:
            continue
    if not parsed:
        return {}
    query = select(DocAsset)
    if document_id is not None:
        query = query.where(DocAsset.document_id == document_id)
    else:
        query = query.where(DocAsset.id.in_(parsed))
    rows = (await session.scalars(query)).all()
    by_id = {row.id: row for row in rows}
    aliases: dict[str, tuple[DocAsset, str]] = {}
    for row in rows:
        raw_aliases = (row.meta or {}).get("aliases")
        if isinstance(raw_aliases, dict):
            for alias, key in raw_aliases.items():
                if isinstance(alias, str) and isinstance(key, str):
                    aliases[alias] = (row, key)
    images: dict[str, str] = {}
    for asset_id in asset_ids:
        try:
            parsed_id = UUID(asset_id)
        except ValueError:
            continue
        resolved: DocAsset | None = by_id.get(parsed_id)
        storage_key = resolved.storage_key if resolved is not None else None
        if resolved is None and asset_id in aliases:
            resolved, storage_key = aliases[asset_id]
        if resolved is None or resolved.kind != "image" or not storage_key:
            continue
        try:
            blob = await storage.get_bytes(storage_key)
        except Exception:
            continue
        mime = resolved.mime or mimetypes.guess_type(storage_key)[0] or "image/png"
        images[asset_id] = f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"
    return images


async def _cached_artifact(
    session: AsyncSession, deck_id: UUID, fmt: str, digest: str
) -> ExportArtifact | None:
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(ExportArtifact)
            .where(
                ExportArtifact.deck_id == deck_id,
                ExportArtifact.format == fmt,
                ExportArtifact.schema_hash == digest,
            )
            .order_by(ExportArtifact.created_at.desc())
        )
    ).all()
    for row in rows:
        if row.expires_at.replace(tzinfo=UTC) > now:
            return row
    return None


async def create_export(
    session: AsyncSession,
    *,
    deck_row: DeckRow,
    user_id: UUID,
    fmt: str,
    options: dict[str, Any] | None = None,
    version_seq: int | None = None,
    check_cancel: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[ExportArtifact, bool]:
    if fmt not in FORMATS:
        raise ValidationFailedError(f"unsupported export format '{fmt}'")
    if fmt == "mp4":
        raise ConflictError("MP4 由客户端 WebCodecs 管线生成，服务端不提供此格式")

    if check_cancel is not None and await check_cancel():
        raise ConflictError("导出任务已取消")

    seq = version_seq or deck_row.current_version_seq
    payload = await load_deck_at(session, deck_row.id, seq)
    deck = Deck.model_validate(payload)
    document = await session.get(Document, deck.meta.source_document_id) if deck.meta.source_document_id else None
    await ensure_deck_semantics(
        session,
        deck,
        document=document,
        require_non_empty=True,
        expected_deck_id=deck_row.id.hex,
    )
    if not deck.slides:
        raise ValidationFailedError("deck has no slides; generate pages before exporting")

    options = options or {}
    digest = schema_hash(
        {"deck": deck.model_dump(mode="json", by_alias=True), "format": fmt, "options": options}
    )
    cached = await _cached_artifact(session, deck_row.id, fmt, digest)
    if cached is not None:
        return cached, True

    manifest = load_manifest(deck.theme_id)
    manifest_issues = validate_manifest(manifest)
    if manifest_issues:
        raise ValidationFailedError(
            "主题 manifest 校验失败，导出中止", details={"issues": manifest_issues}
        )
    document_id = deck.meta.source_document_id
    images = await _image_map(session, deck, document_id)
    css = theme_css(manifest)
    slides_html = [render_slide_html(slide, images=images) for slide in deck.slides]
    degraded_notes: list[str] = []
    degraded_details: list[dict[str, Any]] = []
    degraded_slides = [slide.id for slide in deck.slides if slide.degraded]
    if degraded_slides:
        degraded_notes.append(f"{len(degraded_slides)} 页为降级页，已按纯文本呈现")
    for idx, slide in enumerate(deck.slides):
        if slide.degraded:
            degraded_details.append(
                {
                    "slideId": slide.id,
                    "slideIndex": idx,
                    "reason": slide.degraded_reason or "unknown",
                }
            )

    if fmt == "html":
        content = build_standalone_html(deck, manifest, images).encode("utf-8")
        content_type = FORMATS["html"]
    elif fmt == "pdf":
        result = await render_pdf(slides_html=slides_html, theme_css=css)
        content = result.content
        content_type = result.content_type
        degraded_notes.extend(result.notes)
    elif fmt == "gif":
        fps = int(options.get("fps") or 15)
        seconds = float(options.get("seconds") or 8)
        frame_count = max(1, int(fps * seconds))
        frame_times = [round(i / fps, 4) for i in range(frame_count)]
        bg_color = (manifest.get("tokens") or {}).get("color", {}).get("bg", "#FFFFFF")
        try:
            dark_theme = relative_luminance(bg_color) < 0.18
        except (ValueError, TypeError):
            dark_theme = False
        slide_steps = [slide.steps for slide in deck.slides]
        result = await render_png_sequence(
            slides_html=slides_html,
            theme_css=css,
            fps=fps,
            seconds=seconds,
            max_width=int(options.get("maxWidth") or 1280),
            frame_times=frame_times,
            dark_theme=dark_theme,
            slide_steps=slide_steps,
        )
        content = result.content
        content_type = result.content_type
        degraded_notes.extend(result.notes)
        degraded_notes.append("GIF 为 256 色，粒子与半透明会被简化；需要保真请改用 PDF/HTML")
    else:
        rendered_pages: dict[int, bytes] = {}
        for index, slide in enumerate(deck.slides):
            has_media_layout = slide.layout in {"chart", "split-lr", "split-tb", "full-image"}
            has_cover_image = (
                slide.layout == "cover"
                and isinstance(slide.slots.get("bg"), dict)
                and slide.slots["bg"].get("kind") == "image"
            )
            if has_media_layout or has_cover_image or slide.elements:
                rendered_pages[index] = await render_png(slides_html[index], css)
        content, notes = build_pptx(
            deck=deck,
            manifest=manifest,
            images=images,
            slides_html=slides_html,
            options=options,
            rendered_pages=rendered_pages,
        )
        content_type = FORMATS["pptx"]
        degraded_notes.extend(notes)

    if check_cancel is not None and await check_cancel():
        raise ConflictError("导出任务已取消")

    key = safe_key(f"exports/{deck_row.id}/{fmt}", SUFFIXES[fmt])
    await storage.put_bytes(key, content, content_type)
    artifact = ExportArtifact(
        deck_id=deck_row.id,
        version_id=(await _version_id(session, deck_row.id, seq)),
        user_id=user_id,
        format=fmt,
        storage_key=key,
        bytes=len(content),
        schema_hash=digest,
        options=options,
        degraded=bool(degraded_notes),
        degraded_notes=degraded_notes,
        degraded_details=degraded_details,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.purge_retention_days),
    )
    session.add(artifact)
    await session.flush()
    return artifact, False


async def _version_id(session: AsyncSession, deck_id: UUID, seq: int) -> UUID:
    from app.db.models import DeckVersion

    version = await session.scalar(
        select(DeckVersion).where(DeckVersion.deck_id == deck_id, DeckVersion.seq == seq)
    )
    if version is None:
        raise NotFoundError("version not found for export")
    return version.id


async def list_artifacts(
    session: AsyncSession, deck_id: UUID, *, owner: UUID
) -> list[ExportArtifact]:
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(ExportArtifact)
            .where(ExportArtifact.deck_id == deck_id, ExportArtifact.user_id == owner)
            .order_by(ExportArtifact.created_at.desc())
            .limit(100)
        )
    ).all()
    return [row for row in rows if row.expires_at.replace(tzinfo=UTC) > now]
