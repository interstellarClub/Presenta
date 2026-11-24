from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.api.schemas.deck import CamelModel


class ShareCreate(CamelModel):
    deck_id: UUID
    password: str = Field(min_length=4, max_length=128)
    ttl_hours: int = Field(default=72, ge=1, le=24 * 365)
    allow_download: bool = True
    formats: list[str] | None = None


class ShareView(CamelModel):
    id: UUID
    slug: str
    url: str
    expires_at: datetime
    allow_download: bool
    download_formats: list[str]
    view_count: int
    revoked_at: datetime | None = None


class GuestInfo(CamelModel):
    title: str
    requires_password: bool
    expires_at: datetime


class UnlockRequest(CamelModel):
    password: str = Field(default="", max_length=128)


class UnlockResponse(CamelModel):
    deck: dict[str, Any]
    version_seq: int
    allow_download: bool
    download_formats: list[str]
    degraded_slides: list[str] = Field(default_factory=list)


class GuestDownload(CamelModel):
    url: str
    degraded: bool
    degraded_notes: list[str] = Field(default_factory=list)
    degraded_details: list[dict[str, Any]] = Field(default_factory=list)
    expires_at: datetime | None = None