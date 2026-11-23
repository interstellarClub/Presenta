import hashlib
import json
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.core.errors import ValidationFailedError
from app.services.deck.layouts import LAYOUTS, display_width

AnimTrigger = Literal["enter", "click", "loop"]
AnimEffect = Literal["fade", "push", "wipe", "slide", "zoom", "appear", "dissolve"]
TransitionEffect = Literal["fade", "push", "wipe", "cover", "zoom"]
ElementType = Literal["text", "image", "chart", "formula", "code", "component", "table", "number"]
ProvenanceType = Literal["original", "derived", "external"]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class SourceRef(CamelModel):
    line_start: int = Field(ge=1)
    col_start: int = Field(ge=0)
    line_end: int = Field(ge=1)
    col_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "SourceRef":
        if (self.line_end, self.col_end) < (self.line_start, self.col_start):
            raise ValueError("sourceRef end precedes start")
        return self


class Provenance(CamelModel):
    type: ProvenanceType
    document_id: uuid.UUID
    source_ref: SourceRef
    quote: str = Field(min_length=1, max_length=4000)
    original_data: dict[str, Any] | list[Any] | None = None
    external_url: str | None = None
    license: str | None = None

    @model_validator(mode="after")
    def _type_rules(self) -> "Provenance":
        if self.type == "derived" and self.original_data is None:
            raise ValueError("derived provenance requires originalData")
        if self.type == "external":
            if not self.external_url or not self.license:
                raise ValueError("external provenance requires externalUrl and license")
        return self


class AnimSpec(CamelModel):
    trigger: AnimTrigger = "enter"
    effect: AnimEffect = "fade"
    delay: int = Field(default=0, ge=0, le=5000)
    duration: int = Field(default=400, ge=0, le=5000)
    easing: str = Field(default="ease-out", max_length=40)


class Transition(CamelModel):
    effect: TransitionEffect = "fade"
    duration: int = Field(default=400, ge=0, le=3000)


class ElementLayout(CamelModel):
    x: float = Field(ge=0, le=12)
    y: float = Field(ge=0, le=100)
    w: float = Field(gt=0, le=12)
    h: float = Field(gt=0, le=100)


class ComponentSpec(CamelModel):
    name: Literal[
        "FlowParticles",
        "StepReveal",
        "ChartReveal",
        "FlowDiagram",
        "FormulaStep",
        "CodeType",
    ]
    config: dict[str, Any] = Field(default_factory=dict)


class Element(CamelModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], max_length=32)
    type: ElementType
    slot_path: str = Field(min_length=1, max_length=64)
    layout: ElementLayout | None = None
    style_override: dict[str, str | int | float] = Field(default_factory=dict)
    anim: list[AnimSpec] = Field(default_factory=list)
    component: ComponentSpec | None = None
    provenance: Provenance | None = None

    @field_validator("style_override")
    @classmethod
    def _style_whitelist(cls, value: dict[str, str | int | float]) -> dict[str, str | int | float]:
        allowed = {
            "fontSize",
            "fontWeight",
            "color",
            "lineHeight",
            "letterSpacing",
            "textAlign",
            "padding",
            "borderRadius",
            "boxShadow",
            "opacity",
            "background",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"styleOverride keys not allowed: {sorted(unknown)}")
        return value


class ImageMedia(CamelModel):
    kind: Literal["image"] = "image"
    asset_id: str = Field(min_length=1, max_length=64)
    alt: str = Field(default="", max_length=120)
    fit: Literal["cover", "contain"] = "cover"

    @field_validator("asset_id")
    @classmethod
    def _asset_only(cls, value: str) -> str:
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "data:", "file:", "/", "\\")):
            raise ValueError("image slots accept asset_id only; external URLs are forbidden")
        return value


class ChartPoint(CamelModel):
    label: str = Field(min_length=1, max_length=32)
    value: float


class ChartSeries(CamelModel):
    name: str = Field(min_length=1, max_length=40)
    points: list[ChartPoint] = Field(min_length=1, max_length=40)


class ChartMedia(CamelModel):
    kind: Literal["chart"] = "chart"
    type: Literal["bar", "line", "pie", "area", "scatter"]
    title: str = Field(default="", max_length=60)
    series: list[ChartSeries] = Field(min_length=1, max_length=6)
    unit: str = Field(default="", max_length=16)


class TableMedia(CamelModel):
    kind: Literal["table"] = "table"
    columns: list[str] = Field(min_length=1, max_length=8)
    rows: list[list[str]] = Field(min_length=1, max_length=20)
    caption: str = Field(default="", max_length=60)

    @model_validator(mode="after")
    def _rectangular(self) -> "TableMedia":
        width = len(self.columns)
        for row in self.rows:
            if len(row) != width:
                raise ValueError("table rows must match column count")
        return self


Media = Annotated[ImageMedia | ChartMedia | TableMedia, Field(discriminator="kind")]


class NumberItem(CamelModel):
    value: str = Field(min_length=1, max_length=6)
    label: str = Field(min_length=1, max_length=24)


class CardItem(CamelModel):
    heading: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=120)


class TimelineNode(CamelModel):
    time: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=80)


class ProcessStep(CamelModel):
    label: str = Field(min_length=1, max_length=24)
    text: str = Field(default="", max_length=80)


class Slide(CamelModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], max_length=32)
    layout: str
    slots: dict[str, Any] = Field(default_factory=dict)
    transition: Transition | None = None
    steps: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=4000)
    degraded: bool = False
    degraded_reason: str | None = None
    elements: list[Element] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_layout(self) -> "Slide":
        issues = validate_slide(self)
        if issues:
            raise ValueError("; ".join(issues))
        return self


class DeckMeta(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=160)
    author: str = Field(default="", max_length=80)
    source_document_id: uuid.UUID | None = None
    language: Literal["zh", "en", "mixed"] = "zh"


class Deck(CamelModel):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=32)
    theme_id: str = Field(default="academic", max_length=64)
    motion_level: float = Field(default=0.0, ge=0.0, le=1.0)
    meta: DeckMeta
    slides: list[Slide] = Field(default_factory=list, max_length=500)
    provenance: list[Provenance] = Field(default_factory=list)


def _check_text(name: str, value: Any, max_chars: float | None) -> list[str]:
    if not isinstance(value, str):
        return [f"{name} must be a string"]
    if not value.strip():
        return [f"{name} must not be empty"]
    if max_chars is not None and display_width(value) > max_chars:
        return [f"{name} exceeds {max_chars} display chars"]
    return []


def _check_list(name: str, value: Any, spec: Any) -> list[str]:
    if not isinstance(value, list):
        return [f"{name} must be a list"]
    issues: list[str] = []
    if spec.min_items is not None and len(value) < spec.min_items:
        issues.append(f"{name} needs at least {spec.min_items} items")
    if spec.max_items is not None and len(value) > spec.max_items:
        issues.append(f"{name} allows at most {spec.max_items} items")
    return issues


def _validate_media(name: str, value: Any, spec: Any) -> list[str]:
    if not isinstance(value, dict):
        return [f"{name} must be a media object"]
    kind = value.get("kind")
    allowed = spec.allowed_media or ("image", "chart", "table")
    if kind not in allowed:
        return [f"{name} kind must be one of {allowed}"]
    try:
        if kind == "image":
            ImageMedia.model_validate(value)
        elif kind == "chart":
            ChartMedia.model_validate(value)
        else:
            TableMedia.model_validate(value)
    except Exception as exc:
        return [f"{name} invalid: {exc}"]
    return []


def validate_slide(slide: Slide) -> list[str]:
    spec = LAYOUTS.get(slide.layout)
    if spec is None:
        return [f"unknown layout '{slide.layout}'"]

    issues: list[str] = []
    unknown = set(slide.slots) - set(spec.slots)
    if unknown:
        issues.append(f"unknown slots for {slide.layout}: {sorted(unknown)}")

    for name, slot in spec.slots.items():
        value = slide.slots.get(name)
        if value in (None, "", []):
            if slot.required:
                issues.append(f"slot '{name}' is required")
            continue
        if slot.kind in {"short_text", "body_text", "source"}:
            issues.extend(_check_text(name, value, slot.max_chars))
            continue
        if slot.kind == "background":
            if isinstance(value, dict):
                issues.extend(_validate_media(name, value, slot))
            elif isinstance(value, str):
                if not (value.startswith("#") or value.isidentifier()):
                    issues.append(f"{name} must be a hex color or theme token")
            else:
                issues.append(f"{name} must be a color token or asset-backed image")
            continue
        if slot.kind == "image":
            issues.extend(_validate_media(name, value, slot))
            continue
        if slot.kind == "media":
            issues.extend(_validate_media(name, value, slot))
            continue
        if slot.kind == "chart":
            if not isinstance(value, dict):
                issues.append(f"{name} must be a chart object")
            else:
                try:
                    ChartMedia.model_validate({**value, "kind": value.get("kind", "chart")})
                except Exception as exc:
                    issues.append(f"{name} invalid: {exc}")
            continue

        if slot.kind == "text_list":
            issues.extend(_check_list(name, value, slot))
            if isinstance(value, list):
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        issues.extend(_check_text(f"{name}[{idx}]", item.get("text", ""), slot.item_max_chars))
                        if slot.item_secondary_max_chars and item.get("sub"):
                            issues.extend(
                                _check_text(
                                    f"{name}[{idx}].sub",
                                    item["sub"],
                                    slot.item_secondary_max_chars,
                                )
                            )
                    else:
                        issues.extend(_check_text(f"{name}[{idx}]", item, slot.item_max_chars))
            continue

        if slot.kind in {"cards", "timeline", "steps", "numbers", "compare"}:
            issues.extend(_check_list(name, value, slot))
            if not isinstance(value, list):
                continue
            for idx, item in enumerate(value):
                if slot.kind == "compare":
                    issues.extend(_check_text(f"{name}[{idx}]", item, slot.item_max_chars))
                    continue
                if not isinstance(item, dict):
                    issues.append(f"{name}[{idx}] must be an object")
                    continue
                missing = [field for field in slot.item_fields if field not in item]
                if missing:
                    issues.append(f"{name}[{idx}] missing fields {missing}")
                    continue
                primary = slot.item_fields[0]
                issues.extend(
                    _check_text(f"{name}[{idx}].{primary}", item.get(primary, ""), slot.item_max_chars)
                )
                if len(slot.item_fields) > 1:
                    secondary = slot.item_fields[1]
                    if item.get(secondary):
                        issues.extend(
                            _check_text(
                                f"{name}[{idx}].{secondary}",
                                item.get(secondary),
                                slot.item_secondary_max_chars,
                            )
                        )
            continue

    if spec.required_provenance and not slide.provenance and not any(e.provenance for e in slide.elements):
        issues.append(f"layout '{slide.layout}' requires provenance with sourceRef and quote")

    return issues


def validate_deck(deck: Deck) -> None:
    if not deck.slides:
        raise ValidationFailedError("deck must contain at least one slide")
    for index, slide in enumerate(deck.slides):
        issues = validate_slide(slide)
        if issues:
            raise ValidationFailedError(
                "slide schema validation failed", details={"slide": index, "issues": issues}
            )


def canonical_json(value: Any) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def schema_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()