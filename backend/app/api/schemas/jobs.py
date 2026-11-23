from datetime import datetime
from typing import Any
from uuid import UUID

from app.api.schemas.deck import CamelModel


class JobView(CamelModel):
    id: UUID
    kind: str
    status: str
    progress: int
    stage: str | None = None
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class JobEvent(CamelModel):
    job: JobView
    terminal: bool