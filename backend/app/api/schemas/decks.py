from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.deck import CamelModel
from app.api.schemas.outline import Outline


class DeckCreate(CamelModel):
    document_id: UUID
    outline: Outline | None = None
    theme_id: str = Field(default="academic", max_length=64)


class PatchSubmit(CamelModel):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    kind: Literal["autosave", "milestone"] = "autosave"
    label: str | None = Field(default=None, max_length=120)
    expected_seq: int | None = Field(default=None, ge=0)


class DeckResponse(CamelModel):
    deck: dict[str, Any]
    version_seq: int
    degraded_slides: list[str] = Field(default_factory=list)
    wcag: dict[str, Any] | None = None


class VersionSummary(CamelModel):
    id: UUID
    seq: int
    parent_id: UUID | None = None
    kind: str
    label: str | None = None
    has_snapshot: bool
    created_at: str


class RollbackRequest(CamelModel):
    target_seq: int = Field(ge=1)


class GenerateResponse(CamelModel):
    job_id: UUID
    version_seq: int


class IntentRequest(CamelModel):
    instruction: str = Field(min_length=2, max_length=1000)
    expected_seq: int | None = Field(default=None, ge=0)


class IntentResponse(CamelModel):
    operations: list[dict[str, Any]]
    explanation: str = ""
    preview: dict[str, Any]
