from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.deck import CamelModel

ExportFormat = Literal["html", "pdf", "pptx", "gif", "mp4"]


class ExportRequest(CamelModel):
    deck_id: UUID
    format: ExportFormat
    options: dict[str, Any] = Field(default_factory=dict)


class ExportArtifactView(CamelModel):
    id: UUID
    format: str
    bytes: int
    degraded: bool
    degraded_notes: list[str] = Field(default_factory=list)
    download_url: str
    expires_at: str


class ExportStart(CamelModel):
    job_id: UUID | None = None
    artifact: ExportArtifactView | None = None
    cached: bool = False