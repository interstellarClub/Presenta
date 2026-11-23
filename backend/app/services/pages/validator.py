import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Provenance, Slide, SourceRef
from app.db.models import DocAsset
from app.services.deck.layouts import LAYOUTS, display_width

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
    if quote and quote in document_text:
        slide.provenance = [
            Provenance(
                type="original",
                document_id=document_id,
                source_ref=section_source_ref(section),
                quote=quote,
            )
        ]
        return True
    return False


def iter_media(slots: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("kind") in {"image", "chart", "table"}:
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

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
    issues: list[str] = []
    expected_provenance = layout_requires_provenance(slide.layout)
    if expected_provenance and not slide.provenance:
        issues.append("缺少 provenance：该版式必须提供 sourceRef 与逐字 quote")
        return issues

    for provenance in slide.provenance:
        if provenance.quote and provenance.quote not in document_text:
            issues.append("provenance.quote 不是原文逐字片段，禁止改写或拼接来源")

    quotes = " ".join(provenance.quote for provenance in slide.provenance)
    normalized_quote = _normalize(quotes)
    for value in collect_chart_values(slide):
        if not any(_normalize(variant) in normalized_quote for variant in _number_variants(value)):
            issues.append(f"图表数值 {value:g} 无法在来源原文中逐字符串匹配")

    for media in iter_media(slide.slots):
        if media.get("kind") == "table" and expected_provenance and not slide.provenance:
            issues.append("表格数据缺少来源标注")

    numbers_slot = slide.slots.get("numbers")
    if isinstance(numbers_slot, list):
        for item in numbers_slot:
            if not isinstance(item, dict):
                continue
            number_text = str(item.get("value") or "").strip()
            if number_text and _normalize(number_text) not in normalized_quote:
                issues.append(f"关键数字 '{number_text}' 无法在来源原文中逐字符串匹配")
    return issues


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
    issues.extend(validate_quotes_and_numbers(slide, document_text))
    issues.extend(await validate_assets(session, slide, document_id))
    return issues