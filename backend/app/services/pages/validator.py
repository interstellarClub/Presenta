import re
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Element, Provenance, Slide, SourceRef
from app.db.models import DocAsset
from app.services.deck.layouts import LAYOUTS, display_width
from app.services.deck.semantics import load_assets_for, slide_semantic_issues

_NUMBER_CLEAN = re.compile(r"[,\s\u00a0]")


def layout_requires_provenance(layout: str) -> bool:
    spec = LAYOUTS.get(layout)
    return bool(spec and spec.required_provenance)


def section_source_ref(section: dict[str, Any]) -> SourceRef:
    return SourceRef(
        line_start=int(section.get("lineStart") or 1),
        col_start=0,
        line_end=int(section.get("lineEnd") or section.get("lineStart") or 1),
        col_end=max(1, len(str(section.get("text") or "").splitlines()[-1]) if section.get("text") else 1),
    )


def attach_section_provenance(
    slide: Slide,
    section: dict[str, Any],
    document_id: UUID,
    document_text: str,
) -> bool:
    if slide.provenance:
        return True
    if not layout_requires_provenance(slide.layout):
        return True
    text = str(section.get("text") or "").strip()
    if not text:
        return False
    quote = text[:400].strip()
    if not quote or quote not in document_text:
        return False

    spec = LAYOUTS.get(slide.layout)
    slot_kinds = {slot.kind for slot in spec.slots.values()} if spec else set()
    provenance_type: Literal["original", "derived"] = "original"
    original_data = None
    if "chart" in slot_kinds:
        provenance_type = "derived"
        chart = slide.slots.get("chart") or {}
        original_data = {
            "columns": ["label", "value"],
            "rows": [
                [point.get("label"), point.get("value")]
                for series in chart.get("series") or []
                for point in series.get("points") or []
            ],
            "unit": chart.get("unit", ""),
        }
    elif "numbers" in slot_kinds:
        provenance_type = "derived"
        original_data = {"numbers": slide.slots.get("numbers") or []}

    slide.provenance = [
        Provenance(
            type=provenance_type,
            document_id=document_id,
            source_ref=section_source_ref(section),
            quote=quote,
            original_data=original_data,
        )
    ]
    return True


def attach_media_provenance(slide: Slide) -> None:
    """Give every media slot an Element with an explicit provenance link."""
    if not slide.provenance and not slide.elements:
        return
    existing = {element.slot_path for element in slide.elements}
    media = iter_media(slide.slots)
    type_map = {"image": "image", "chart": "chart", "table": "table"}
    for index, entry in enumerate(media):
        path = str(entry.get("__path__") or "")
        if not path or path in existing:
            continue
        kind = str(entry.get("kind"))
        if kind not in type_map:
            continue
        provenance: Provenance | None = None
        if slide.provenance:
            if len(media) == len(slide.provenance):
                provenance = slide.provenance[index]
            else:
                provenance = slide.provenance[min(index, len(slide.provenance) - 1)]
        slide.elements.append(
            Element(
                type=type_map[kind],  # type: ignore[arg-type]
                slot_path=path,
                provenance=provenance,
            )
        )


def iter_media(slots: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            if value.get("kind") in {"image", "chart", "table"}:
                found.append({**value, "__path__": path})
                return
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(slots)
    return found


def collect_asset_ids(slide: Slide) -> list[str]:
    ids: list[str] = []
    for media in iter_media(slide.slots):
        if media.get("kind") == "image":
            asset_id = str(media.get("assetId") or "")
            if asset_id:
                ids.append(asset_id)
    return ids


def collect_chart_values(slide: Slide) -> list[float]:
    values: list[float] = []
    for media in iter_media(slide.slots):
        if media.get("kind") != "chart":
            continue
        for series in media.get("series") or []:
            for point in series.get("points") or []:
                raw = point.get("value")
                if isinstance(raw, (int, float)):
                    values.append(float(raw))
    return values


def _number_variants(value: float) -> list[str]:
    variants = {f"{value:g}", f"{value:.0f}" if value.is_integer() else f"{value:g}"}
    if value.is_integer():
        variants.add(str(int(value)))
    variants.add(f"{value:,.1f}".rstrip("0").rstrip("."))
    variants.add(f"{value:,.2f}".rstrip("0").rstrip("."))
    return [variant for variant in variants if variant]


def _normalize(text: str) -> str:
    return _NUMBER_CLEAN.sub("", text)


def validate_quotes_and_numbers(slide: Slide, document_text: str) -> list[str]:
    document_id = slide.provenance[0].document_id if slide.provenance else UUID(int=0)
    return slide_semantic_issues(
        slide, document_id=document_id, document_text=document_text, assets={}
    )


async def validate_assets(
    session: AsyncSession, slide: Slide, document_id: UUID
) -> list[str]:
    ids = collect_asset_ids(slide)
    if not ids:
        return []
    try:
        parsed = [UUID(asset_id) for asset_id in ids]
    except ValueError:
        return ["图片 assetId 必须是文档资产表中的 id"]

    rows = (
        await session.scalars(
            select(DocAsset).where(
                DocAsset.id.in_(parsed), DocAsset.document_id == document_id
            )
        )
    ).all()
    found = {row.id for row in rows}
    missing = [asset_id for asset_id, uuid_value in zip(ids, parsed, strict=False) if uuid_value not in found]
    return [f"图片 assetId 不在本文档资产表中：{missing}"] if missing else []


def validate_lengths(slide: Slide) -> list[str]:
    spec = LAYOUTS.get(slide.layout)
    if spec is None:
        return [f"未知版式 '{slide.layout}'"]
    issues: list[str] = []
    title = slide.slots.get("title")
    if isinstance(title, str) and display_width(title) > 24:
        issues.append("标题超过 24 字符")
    return issues


async def semantic_issues(
    session: AsyncSession,
    slide: Slide,
    *,
    document_id: UUID,
    document_text: str,
) -> list[str]:
    issues: list[str] = []
    issues.extend(validate_lengths(slide))
    parsed: list[UUID] = []
    for asset_id in collect_asset_ids(slide):
        try:
            parsed.append(UUID(asset_id))
        except ValueError:
            issues.append(f"图片 assetId 非法：{asset_id}")
    assets = await load_assets_for(session, document_id, set(parsed))
    issues.extend(
        slide_semantic_issues(
            slide,
            document_id=document_id,
            document_text=document_text,
            assets=assets,
        )
    )
    return issues