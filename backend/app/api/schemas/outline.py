from pydantic import Field, model_validator

from app.api.schemas.deck import CamelModel


class OutlineItem(CamelModel):
    id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=24)
    points: list[str] = Field(min_length=1, max_length=6)
    section_id: str | None = Field(default=None, max_length=64)
    layout_hint: str | None = Field(default=None, max_length=32)


class Outline(CamelModel):
    title: str = Field(min_length=1, max_length=60)
    subtitle: str = Field(default="", max_length=80)
    items: list[OutlineItem] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Outline":
        seen: set[str] = set()
        for item in self.items:
            if item.id in seen:
                raise ValueError(f"duplicate outline item id '{item.id}'")
            seen.add(item.id)
        return self