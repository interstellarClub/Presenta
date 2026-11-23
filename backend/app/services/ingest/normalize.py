import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.services.ingest.assets import persist_docx_assets
from app.services.ingest.docx import DocxResult, docx_to_markdown
from app.services.ingest.markdown import build_ast
from app.services.storage import storage


class IngestError(Exception):
    def __init__(self, message: str, *, degraded: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.degraded = degraded


async def _decode_markdown(blob: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="replace")


async def parse_docx_blob(blob: bytes) -> DocxResult:
    with tempfile.TemporaryDirectory(prefix="presenta-docx-") as tmp:
        path = Path(tmp) / "source.docx"
        path.write_bytes(blob)
        return docx_to_markdown(path)


async def ingest_document(
    session: AsyncSession,
    document: Document,
    *,
    progress: Any = None,
    check_cancel: Any = None,
) -> dict[str, Any]:
    async def notify(stage: str, percent: int) -> None:
        document.status = stage if stage in {
            "normalizing",
            "extracting_assets",
            "indexing",
            "ready",
        } else document.status
        if progress is not None:
            await progress(percent, stage)

    if check_cancel is not None and await check_cancel():
        raise IngestError("cancelled")

    await notify("normalizing", 10)
    if not document.original_key:
        raise IngestError("document has no stored source file")

    blob = await storage.get_bytes(document.original_key)
    degraded_reasons: list[str] = []

    if document.source_type == "upload_docx":
        result = await parse_docx_blob(blob)
        await notify("extracting_assets", 45)
        await persist_docx_assets(session, document, result)
        normalized = result.markdown
        degraded_reasons.extend(result.degraded)
    else:
        normalized = await _decode_markdown(blob)
        if not normalized.strip():
            raise IngestError("markdown source is empty")

    await notify("indexing", 70)
    ast = build_ast(normalized)
    if not ast.get("sections"):
        raise IngestError("document produced no sections")

    document.normalized_md = normalized
    document.ast = ast
    document.degraded = bool(degraded_reasons)
    document.error = {"degradedReasons": degraded_reasons} if degraded_reasons else None
    await notify("ready", 100)
    await session.flush()

    return {
        "sections": len(ast["sections"]),
        "blocks": len(ast["blocks"]),
        "degraded": document.degraded,
        "degradedReasons": degraded_reasons,
    }