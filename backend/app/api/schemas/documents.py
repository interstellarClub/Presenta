from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.api.schemas.deck import CamelModel
from app.api.schemas.outline import Outline


class EditorDocumentCreate(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=2_000_000)


class MarkdownUpdate(CamelModel):
    markdown: str = Field(min_length=1, max_length=2_000_000)


class AssetSummary(CamelModel):
    id: str
    kind: str
    mime: str | None = None
    source_ref: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


class SectionNode(CamelModel):
    id: str
    title: str
    level: int
    parent_id: str | None = None
    line_start: int
    line_end: int
    preview: str = ""


class DocumentSummary(CamelModel):
    id: UUID
    title: str
    source_type: str
    status: str
    degraded: bool
    created_at: datetime
    updated_at: datetime
    section_count: int = 0
    asset_count: int = 0
    has_outline: bool = False


class DocumentDetail(DocumentSummary):
    normalized_md: str = ""
    sections: list[SectionNode] = Field(default_factory=list)
    assets: list[AssetSummary] = Field(default_factory=list)
    outline: Outline | None = None
    error: dict[str, Any] | None = None


class DocumentCreated(CamelModel):
    document: DocumentSummary
    job_id: UUID | None = None