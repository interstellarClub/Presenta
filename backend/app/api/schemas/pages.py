from typing import Any

from pydantic import Field

from app.api.schemas.deck import CamelModel, Provenance, Slide
from app.core.errors import ValidationFailedError


class PageDraft(CamelModel):
    layout: str = Field(min_length=1, max_length=32)
    slots: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)
    provenance: list[Provenance] = Field(default_factory=list, max_length=8)


def draft_to_slide(draft: PageDraft, *, slide_id: str | None = None) -> Slide:
    payload: dict[str, Any] = {
        "layout": draft.layout,
        "slots": draft.slots,
        "notes": draft.notes,
        "provenance": [entry.model_dump(mode="json", by_alias=True) for entry in draft.provenance],
    }
    if slide_id:
        payload["id"] = slide_id
    try:
        return Slide.model_validate(payload)
    except Exception as exc:
        raise ValidationFailedError(
            "page draft does not satisfy slide schema",
            details={"layout": draft.layout, "errors": str(exc)[:3000]},
        ) from exc