import json
import zipfile
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.documents import (
    AssetSummary,
    DocumentCreated,
    DocumentDetail,
    DocumentSummary,
    EditorDocumentCreate,
    MarkdownUpdate,
    SectionNode,
)
from app.api.schemas.outline import Outline
from app.core.audit import audit
from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep, ensure_owner
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.db.models import Deck, DocAsset, Document, Job
from app.services.ingest.markdown import summarize_section
from app.services.jobs import create_job, enqueue_job
from app.services.outline.generator import confirm_outline, stream_outline
from app.services.storage import safe_key, storage

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_SUFFIXES = {".docx", ".md", ".markdown"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_ALLOWED_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "text/markdown",
    "text/plain",
}


def _validate_docx_zip(blob: bytes) -> None:
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(blob)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValidationFailedError(f"docx 包损坏：{exc}") from exc
    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > settings.max_docx_uncompressed_bytes:
        raise PayloadTooLargeError(
            f"docx 展开后超过 {settings.max_docx_uncompressed_mb}MB 上限"
        )
    compressed = sum(info.compress_size for info in infos) or 1
    ratio = total_uncompressed / compressed
    if ratio > settings.max_docx_compression_ratio:
        raise ValidationFailedError(
            f"docx 压缩比 {ratio:.1f} 超过 {settings.max_docx_compression_ratio} 上限，疑似 zip 炸弹"
        )


async def _owned_document(session: SessionDep, document_id: UUID, user_id: UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFoundError("文档不存在")
    ensure_owner(document.user_id, user_id)
    return document


def _summary(document: Document, *, section_count: int = 0, asset_count: int = 0) -> DocumentSummary:
    ast = document.ast or {}
    return DocumentSummary(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        status=document.status,
        degraded=document.degraded,
        created_at=document.created_at,
        updated_at=document.updated_at,
        section_count=section_count or len(ast.get("sections") or []),
        asset_count=asset_count,
        has_outline=bool(document.outline),
    )


def _detail(document: Document, assets: list[DocAsset]) -> DocumentDetail:
    ast = document.ast or {}
    sections = [
        SectionNode(
            id=section.get("id") or "",
            title=section.get("title") or "",
            level=int(section.get("level") or 1),
            parent_id=section.get("parentId"),
            line_start=int(section.get("lineStart") or 1),
            line_end=int(section.get("lineEnd") or 1),
            preview=summarize_section(str(section.get("text") or ""), 120),
        )
        for section in ast.get("sections") or []
    ]
    asset_summaries = [
        AssetSummary(
            id=asset.id.hex,
            kind=asset.kind,
            mime=asset.mime,
            source_ref=asset.source_ref,
            meta=_trim_meta(asset),
        )
        for asset in assets
    ]
    outline = Outline.model_validate(document.outline) if document.outline else None
    return DocumentDetail(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        status=document.status,
        degraded=document.degraded,
        created_at=document.created_at,
        updated_at=document.updated_at,
        section_count=len(sections),
        asset_count=len(asset_summaries),
        has_outline=bool(outline),
        normalized_md=document.normalized_md or "",
        sections=sections,
        assets=asset_summaries,
        outline=outline,
        error=document.error,
    )


def _trim_meta(asset: DocAsset) -> dict[str, Any] | None:
    if asset.meta is None:
        return None
    meta = dict(asset.meta)
    if "rows" in meta and isinstance(meta["rows"], list):
        meta["rows"] = meta["rows"][:8]
        meta["truncated"] = True
    if "aliases" in meta:
        meta.pop("aliases", None)
    return meta


async def _asset_counts(session: SessionDep, document_ids: list[UUID]) -> dict[UUID, int]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(DocAsset.document_id, func.count(DocAsset.id))
        .where(DocAsset.document_id.in_(document_ids))
        .group_by(DocAsset.document_id)
    )
    return {row[0]: int(row[1]) for row in rows.all()}


@router.post("", response_model=DocumentCreated, status_code=201)
async def upload_document(
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> DocumentCreated:
    filename = (file.filename or "").strip()
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValidationFailedError("仅支持 .docx / .md / .markdown 文件")

    declared_mime = (file.content_type or "").lower()
    if declared_mime and declared_mime not in _ALLOWED_MIME:
        raise ValidationFailedError(f"不支持的 MIME 类型：{declared_mime}")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise PayloadTooLargeError(f"文件超过 {settings.max_upload_mb}MB 上限")
        chunks.append(chunk)
    blob = b"".join(chunks)
    if not blob:
        raise ValidationFailedError("文件为空")

    if suffix == ".docx":
        if not blob.startswith(b"PK\x03\x04"):
            raise ValidationFailedError("文件不是有效的 .docx 包")
        _validate_docx_zip(blob)

    source_type = "editor_md" if suffix in _MARKDOWN_SUFFIXES else "upload_docx"
    key = safe_key(f"documents/{user.id}/originals", suffix.lstrip("."))
    await storage.put_bytes(key, blob, file.content_type or "application/octet-stream")

    document = Document(
        user_id=user.id,
        title=(title or filename.rsplit(".", 1)[0] or "未命名文档")[:200],
        source_type=source_type,
        original_key=key,
        status="parsing",
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)

    job: Job | None = None
    try:
        job = await create_job(
            session,
            user_id=user.id,
            kind="ingest",
            payload={"documentId": str(document.id)},
            idempotency_key=f"doc:{document.id}",
            max_attempts=2,
        )
    except ConflictError:
        job = None

    await audit(
        session,
        action="document.upload",
        user_id=user.id,
        target_type="document",
        target_id=str(document.id),
        request=request,
        meta={"bytes": total, "sourceType": source_type},
    )
    if job is not None:
        await session.commit()
        await enqueue_job(job.id, kind=job.kind)
    return DocumentCreated(document=_summary(document), job_id=job.id if job else None)


@router.post("/editor", response_model=DocumentCreated, status_code=201)
async def create_from_editor(
    payload: EditorDocumentCreate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DocumentCreated:
    key = safe_key(f"documents/{user.id}/originals", "md")
    await storage.put_bytes(key, payload.markdown.encode("utf-8"), "text/markdown")
    document = Document(
        user_id=user.id,
        title=payload.title[:200],
        source_type="editor_md",
        original_key=key,
        status="parsing",
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)
    job = await create_job(
        session,
        user_id=user.id,
        kind="ingest",
        payload={"documentId": str(document.id)},
        idempotency_key=f"doc:{document.id}",
        max_attempts=2,
    )
    await audit(
        session,
        action="document.create_editor",
        user_id=user.id,
        target_type="document",
        target_id=str(document.id),
        request=request,
    )
    await session.commit()
    await enqueue_job(job.id, kind=job.kind)
    return DocumentCreated(document=_summary(document), job_id=job.id)


@router.get("", response_model=list[DocumentSummary])
async def list_documents(user: CurrentUser, session: SessionDep) -> list[DocumentSummary]:
    documents = (
        await session.scalars(
            select(Document)
            .where(Document.user_id == user.id)
            .order_by(Document.created_at.desc())
            .limit(100)
        )
    ).all()
    counts = await _asset_counts(session, [document.id for document in documents])
    return [_summary(document, asset_count=counts.get(document.id, 0)) for document in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID, user: CurrentUser, session: SessionDep
) -> DocumentDetail:
    document = await _owned_document(session, document_id, user.id)
    assets = (
        await session.scalars(
            select(DocAsset)
            .where(DocAsset.document_id == document.id)
            .order_by(DocAsset.kind, DocAsset.created_at)
        )
    ).all()
    return _detail(document, list(assets))


@router.put("/{document_id}/markdown", response_model=DocumentCreated)
async def update_markdown(
    document_id: UUID,
    payload: MarkdownUpdate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DocumentCreated:
    document = await _owned_document(session, document_id, user.id)
    key = document.original_key or safe_key(f"documents/{user.id}/originals", "md")
    await storage.put_bytes(key, payload.markdown.encode("utf-8"), "text/markdown")
    document.original_key = key
    document.source_type = "editor_md"
    document.status = "parsing"
    document.ast = None
    document.error = None
    await session.flush()
    await session.refresh(document)
    job = await create_job(
        session,
        user_id=user.id,
        kind="ingest",
        payload={"documentId": str(document.id)},
        idempotency_key=f"doc:{document.id}:{int(datetime.now(UTC).timestamp())}",
        max_attempts=2,
    )
    await audit(
        session,
        action="document.update_markdown",
        user_id=user.id,
        target_type="document",
        target_id=str(document.id),
        request=request,
    )
    await session.commit()
    await enqueue_job(job.id, kind=job.kind)
    return DocumentCreated(document=_summary(document), job_id=job.id)


@router.post("/{document_id}/outline")
async def generate_outline_stream(
    document_id: UUID, user: CurrentUser, session: SessionDep
) -> EventSourceResponse:
    document = await _owned_document(session, document_id, user.id)
    if document.status != "ready":
        raise ConflictError("文档尚未完成解析，请稍后再试")

    async def event_source() -> Any:
        try:
            async for event, data in stream_outline(session, document, user_id=user.id):
                yield {"event": event, "data": json.dumps(data, ensure_ascii=False)}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)[:500]}, ensure_ascii=False),
            }

    return EventSourceResponse(event_source(), ping=15)


@router.post("/{document_id}/outline/confirm", response_model=DocumentDetail)
async def confirm(
    document_id: UUID,
    outline: Outline,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
) -> DocumentDetail:
    document = await _owned_document(session, document_id, user.id)
    await confirm_outline(session, document, outline)
    await audit(
        session,
        action="document.outline_confirm",
        user_id=user.id,
        target_type="document",
        target_id=str(document.id),
        request=request,
        meta={"items": len(outline.items)},
    )
    assets = (
        await session.scalars(select(DocAsset).where(DocAsset.document_id == document.id))
    ).all()
    return _detail(document, list(assets))


@router.get("/{document_id}/assets/{asset_id}")
async def get_asset(
    document_id: UUID, asset_id: str, user: CurrentUser, session: SessionDep
) -> Response:
    document = await _owned_document(session, document_id, user.id)
    try:
        parsed = UUID(hex=asset_id)
    except ValueError as exc:
        raise ValidationFailedError("assetId 非法") from exc
    asset = await session.get(DocAsset, parsed)
    storage_key = asset.storage_key if asset is not None else None
    if asset is None or asset.document_id != document.id:
        assets = (
            await session.scalars(
                select(DocAsset).where(
                    DocAsset.document_id == document.id, DocAsset.kind == "image"
                )
            )
        ).all()
        for candidate in assets:
            aliases = (candidate.meta or {}).get("aliases")
            if isinstance(aliases, dict) and asset_id in aliases:
                asset = candidate
                storage_key = aliases[asset_id]
                break
    if asset is None or asset.document_id != document.id:
        raise NotFoundError("资产不存在")
    if not storage_key or asset.kind != "image":
        raise ValidationFailedError("该资产没有可下载内容")
    data = await storage.get_bytes(str(storage_key))
    return Response(
        content=data,
        media_type=asset.mime or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{document_id}/decks", response_model=list[dict[str, Any]])
async def list_document_decks(
    document_id: UUID, user: CurrentUser, session: SessionDep
) -> list[dict[str, Any]]:
    document = await _owned_document(session, document_id, user.id)
    decks = (
        await session.scalars(
            select(Deck)
            .where(Deck.document_id == document.id, Deck.deleted_at.is_(None))
            .order_by(Deck.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(deck.id),
            "title": deck.title,
            "themeId": deck.theme_id,
            "motionLevel": deck.motion_level,
            "versionSeq": deck.current_version_seq,
            "createdAt": deck.created_at.isoformat(),
        }
        for deck in decks
    ]
