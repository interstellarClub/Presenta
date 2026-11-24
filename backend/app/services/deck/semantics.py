import copy
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deck import Deck, Provenance, Slide, SourceRef
from app.core.config import settings
from app.core.errors import ValidationFailedError
from app.db.models import DocAsset, Document
from app.services.deck.layouts import LAYOUTS

SUPPORTED_SCHEMA_VERSIONS = {1, 2}
CURRENT_SCHEMA_VERSION = 2
NUMBER_WINDOW = 180


class NumberToken:
    __slots__ = ("text", "value", "start", "end")

    def __init__(self, text: str, value: Decimal, start: int, end: int) -> None:
        self.text = text
        self.value = value
        self.start = start
        self.end = end

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"NumberToken({self.text!r}, {self.value})"


_NUMBER_RE = re.compile(r"(?<![\d.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.])")
_PAREN_NUMBER_RE = re.compile(r"[（(]\s*([-+]?\d+(?:\.\d+)?)\s*[)）]")
_SPACE_RE = re.compile(r"[\s\u00a0]+")
_CLAUSE_RE = re.compile(r"[，,、;；。！!？?\n\r/|]+")
_BRACKET_RE = re.compile(r"[（）()\[\]【】]")


def _to_decimal(raw: str) -> Decimal | None:
    candidate = raw.replace(",", "").replace(" ", "")
    try:
        return Decimal(candidate)
    except InvalidOperation:
        return None


def number_tokens(text: str) -> list[NumberToken]:
    tokens: list[NumberToken] = []
    for match in _NUMBER_RE.finditer(text):
        value = _to_decimal(match.group(0))
        if value is not None:
            tokens.append(NumberToken(match.group(0), value, match.start(), match.end()))
    for match in _PAREN_NUMBER_RE.finditer(text):
        value = _to_decimal(match.group(1))
        if value is not None:
            tokens.append(NumberToken(match.group(1), value, match.start(1), match.end(1)))
    return tokens


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub("", text).casefold()


def bounded_value_present(text: str, value: float | str | Decimal) -> bool:
    try:
        target = Decimal(str(value))
    except InvalidOperation:
        return False
    return any(token.value == target for token in number_tokens(text))


def _occurrences(text: str, needle: str) -> list[int]:
    cleaned = normalize_text(needle)
    if not cleaned:
        return []
    haystack = normalize_text(text)
    positions: list[int] = []
    start = haystack.find(cleaned)
    while start >= 0:
        positions.append(start)
        start = haystack.find(cleaned, start + 1)
    return positions


def _region_bounds(text: str, ref: SourceRef) -> tuple[int, int] | None:
    lines = text.splitlines()
    if not lines:
        return None
    if ref.line_start < 1 or ref.line_end < ref.line_start or ref.line_end > len(lines):
        return None
    first_line = lines[ref.line_start - 1]
    last_line = lines[ref.line_end - 1]
    if ref.col_start < 0 or ref.col_start > len(first_line):
        return None
    if ref.col_end < 0 or ref.col_end > len(last_line):
        return None
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    start = offsets[ref.line_start - 1] + ref.col_start
    end = offsets[ref.line_end - 1] + ref.col_end
    if end < start:
        return None
    return start, end


def document_region(text: str, ref: SourceRef) -> str | None:
    bounds = _region_bounds(text, ref)
    if bounds is None:
        return None
    return text[bounds[0] : bounds[1]]


def _clauses(region: str) -> list[str]:
    cleaned = _BRACKET_RE.sub(" ", region)
    return [clause for clause in _CLAUSE_RE.split(cleaned) if clause.strip()]


def _clause_matches(clause: str, *, target: Decimal, unit: str | None) -> bool:
    if not any(token.value == target for token in number_tokens(clause)):
        return False
    if unit is not None and unit.strip():
        if normalize_text(unit) not in normalize_text(clause):
            return False
    return True


def value_bound_to_label(
    region: str,
    *,
    label: str | None,
    value: float | str | Decimal,
    unit: str | None = None,
) -> bool:
    try:
        target = Decimal(str(value))
    except InvalidOperation:
        return False
    if not label:
        return any(token.value == target for token in number_tokens(region))
    clauses = _clauses(region) or [region]
    labelled = [clause for clause in clauses if normalize_text(label) in normalize_text(clause)]
    for clause in labelled:
        if _clause_matches(clause, target=target, unit=unit):
            return True
    if labelled:
        return False
    for position in _occurrences(region, label):
        window_start = max(0, position - NUMBER_WINDOW)
        window_end = min(len(region), position + len(label) + NUMBER_WINDOW)
        window = region[window_start:window_end]
        if _clause_matches(window, target=target, unit=unit):
            return True
    return False


def _provenance_region(
    provenance: Provenance, document_text: str
) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    region = document_region(document_text, provenance.source_ref)
    if region is None:
        issues.append(
            f"provenance.sourceRef 超出原文范围 (L{provenance.source_ref.line_start}-L{provenance.source_ref.line_end})"
        )
        return None, issues
    quote = provenance.quote.strip()
    if not quote:
        issues.append("provenance.quote 不能为空")
    elif quote not in region:
        issues.append("provenance.quote 与 sourceRef 指向的原文区间不一致")
    return region, issues


def _iter_slots(value: Any, path: str = "") -> list[tuple[str, Any]]:
    entries: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        if value.get("kind") in {"image", "chart", "table"}:
            entries.append((path, value))
        for key, child in value.items():
            entries.extend(_iter_slots(child, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            entries.extend(_iter_slots(child, f"{path}[{index}]"))
    return entries


def _media_entries(slide: Slide) -> list[tuple[str, dict[str, Any]]]:
    return [
        (path, media)
        for path, media in _iter_slots(slide.slots)
        if isinstance(media, dict) and media.get("kind") in {"image", "chart", "table"}
    ]


def _chart_original_data(chart: dict[str, Any]) -> dict[str, Any]:
    return {
        "columns": ["label", "value"],
        "rows": [
            [point.get("label"), point.get("value")]
            for series in chart.get("series") or []
            for point in series.get("points") or []
        ],
        "unit": chart.get("unit", ""),
    }


def _migrate_slide_provenance(slide: dict[str, Any]) -> None:
    provenance = slide.get("provenance") or []
    if not provenance:
        return
    charts = [
        media
        for path, media in _iter_slots(slide.get("slots") or {})
        if isinstance(media, dict) and media.get("kind") == "chart"
    ]
    originals = [entry for entry in provenance if entry.get("type") == "original"]
    if not originals:
        return

    migrated: list[dict[str, Any]] = [
        entry for entry in provenance if entry.get("type") != "original"
    ]
    if charts:
        for index, chart in enumerate(charts):
            base = copy.deepcopy(originals[min(index, len(originals) - 1)])
            base["type"] = "derived"
            base["originalData"] = _chart_original_data(chart)
            migrated.insert(index, base)
    else:
        numbers = (slide.get("slots") or {}).get("numbers")
        for index, entry in enumerate(originals):
            cloned = copy.deepcopy(entry)
            if index == 0 and isinstance(numbers, list) and numbers:
                cloned["type"] = "derived"
                cloned["originalData"] = {"numbers": numbers}
            migrated.append(cloned)
    slide["provenance"] = migrated


def migrate_deck_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy v1 payloads to current schema without mutating the snapshot."""
    if not isinstance(payload, dict):
        return payload
    version = int(payload.get("schemaVersion") or 1)
    if version >= CURRENT_SCHEMA_VERSION:
        return payload
    migrated = copy.deepcopy(payload)
    for slide in migrated.get("slides") or []:
        if isinstance(slide, dict):
            _migrate_slide_provenance(slide)
    migrated["schemaVersion"] = CURRENT_SCHEMA_VERSION
    return migrated


def _slide_issue_prefix(index: int, slide: Slide) -> str:
    return f"slide[{index}] {slide.id}({slide.layout})"


def _original_data_issues(provenance: Provenance, chart_points: list[tuple[str, Decimal]], unit: str) -> list[str]:
    data = provenance.original_data
    if not isinstance(data, dict) or not data:
        return ["derived provenance.originalData 不能为空对象"]
    rows = data.get("rows")
    columns = data.get("columns")
    if isinstance(rows, list) and isinstance(columns, list):
        if not rows or not columns:
            return ["originalData 的 columns/rows 不能为空"]
        if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
            return ["originalData.rows 必须与 columns 列数一致"]
        stored: list[tuple[str, Decimal]] = []
        for row in rows:
            if len(row) < 2:
                continue
            label = str(row[0]).strip()
            for cell in row[1:]:
                for token in number_tokens(str(cell)):
                    stored.append((label, token.value))
        if not stored:
            return ["originalData 没有可核对的数据点"]
        for label, value in chart_points:
            if not any(stored_label == label and stored_value == value for stored_label, stored_value in stored):
                return [f"originalData 缺少图表数据点 {label}={value}"]
        chart_values = {value for _, value in chart_points}
        for _, value in stored:
            if value not in chart_values:
                return [f"originalData 含有图表之外的数值 {value}"]
        stored_unit = str(data.get("unit") or "").strip()
        if unit and stored_unit and normalize_text(unit) != normalize_text(stored_unit):
            return ["originalData.unit 与图表单位不一致"]
        return []
    numbers = data.get("numbers")
    if isinstance(numbers, list):
        if not numbers:
            return ["originalData.numbers 不能为空"]
        return []
    return ["originalData 结构不受支持（需要 columns/rows 或 numbers）"]


def _asset_source_ref(asset: DocAsset) -> SourceRef | None:
    raw = asset.source_ref
    if not isinstance(raw, dict):
        return None
    try:
        return SourceRef(
            line_start=int(raw.get("lineStart") or raw.get("line_start") or 0),
            col_start=int(raw.get("colStart") or raw.get("col_start") or 0),
            line_end=int(raw.get("lineEnd") or raw.get("line_end") or 0),
            col_end=int(raw.get("colEnd") or raw.get("col_end") or 0),
        )
    except (TypeError, ValueError):
        return None


def _refs_overlap(left: SourceRef, right: SourceRef, document_text: str) -> bool:
    left_bounds = _region_bounds(document_text, left)
    right_bounds = _region_bounds(document_text, right)
    if left_bounds is None or right_bounds is None:
        return not (left.line_end < right.line_start or right.line_end < left.line_start)
    return not (left_bounds[1] <= right_bounds[0] or right_bounds[1] <= left_bounds[0])


def _table_fits(region: str, rows: list[Any]) -> bool:
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        label = str(row[0]).strip()
        if label and label not in region:
            return False
        for cell in row[1:]:
            cell_text = str(cell).strip()
            tokens = number_tokens(cell_text)
            if tokens:
                if not all(
                    value_bound_to_label(region, label=label or None, value=token.value)
                    for token in tokens
                ):
                    return False
            elif cell_text and normalize_text(cell_text) not in normalize_text(region):
                return False
    return True


def slide_semantic_issues(
    slide: Slide,
    *,
    document_id: UUID,
    document_text: str,
    assets: dict[UUID, DocAsset],
) -> list[str]:
    issues: list[str] = []
    spec = LAYOUTS.get(slide.layout)
    if spec is None:
        return [f"未知版式 '{slide.layout}'"]

    provenance_regions: list[tuple[Provenance, str]] = []
    for provenance in slide.provenance:
        if provenance.type == "external" and not settings.allow_external_provenance:
            issues.append("external provenance 默认关闭，需显式开启配置并保留审计")
            continue
        if provenance.document_id != document_id:
            issues.append("provenance.documentId 与 Deck 关联文档不一致")
            continue
        region, provenance_issues = _provenance_region(provenance, document_text)
        issues.extend(provenance_issues)
        if region is not None:
            provenance_regions.append((provenance, region))

    for element in slide.elements:
        if element.provenance is None:
            continue
        if element.provenance.document_id != document_id:
            issues.append(f"element {element.id}: provenance.documentId 与 Deck 关联文档不一致")
            continue
        _, element_issues = _provenance_region(element.provenance, document_text)
        issues.extend(f"element {element.id}: {issue}" for issue in element_issues)

    requires_source = any(slot.kind == "source" for slot in spec.slots.values())
    if requires_source and not slide.provenance:
        issues.append("该版式必须关联至少一条 Provenance，source 插槽不能是孤立字符串")
    if spec.required_provenance and not slide.provenance:
        issues.append("该版式缺少 provenance（sourceRef + 逐字 quote）")

    quote_value = slide.slots.get("quote")
    if isinstance(quote_value, str) and quote_value.strip():
        quote_text = quote_value.strip()
        if not provenance_regions:
            issues.append("引用页必须提供可定位的 provenance")
        elif not any(
            quote_text in provenance.quote and quote_text in region
            for provenance, region in provenance_regions
        ):
            issues.append("引用文本必须同时出现在 provenance.quote 与 sourceRef 指向的原文区间")

    chart_sources: list[tuple[str, int]] = []
    table_sources: list[tuple[str, int]] = []

    for path, media in _media_entries(slide):
        if media.get("kind") == "chart":
            series_list = media.get("series") or []
            unit = str(media.get("unit") or "").strip()
            points: list[tuple[str, Decimal]] = []
            if not series_list:
                issues.append(f"{path}: 图表缺少 series")
            for series in series_list:
                series_name = str(series.get("name") or "").strip()
                if series_name and provenance_regions and not any(
                    normalize_text(series_name) in normalize_text(region)
                    for _, region in provenance_regions
                ):
                    issues.append(f"{path}: 系列名 '{series_name}' 未出现在任何来源区间")
                for point in series.get("points") or []:
                    label = str(point.get("label") or "").strip()
                    value = point.get("value")
                    if not label:
                        issues.append(f"{path}: 数据点缺少 label")
                        continue
                    try:
                        points.append((label, Decimal(str(value))))
                    except InvalidOperation:
                        issues.append(f"{path}: 数据点 {label} 的 value 不是数字")
                        continue

            matched: list[tuple[int, Provenance]] = []
            for index, (provenance, region) in enumerate(provenance_regions):
                if provenance.type != "derived" or provenance.original_data is None:
                    continue
                if all(
                    value_bound_to_label(region, label=label, value=value, unit=unit)
                    for label, value in points
                ):
                    matched.append((index, provenance))
            if not matched:
                for label, value in points:
                    if not any(
                        value_bound_to_label(region, label=label, value=value, unit=unit)
                        for _, region in provenance_regions
                    ):
                        issues.append(
                            f"{path}: 数值 {value} 无法与标签 '{label}'"
                            f"{(' 和单位 ' + unit) if unit else ''} 在来源区间内绑定"
                        )
                issues.append(f"{path}: 缺少与图表数据匹配的 derived provenance（含 originalData）")
                continue

            chosen_index: int | None = None
            data_issues: list[str] = []
            for index, provenance in matched:
                candidate_issues = _original_data_issues(provenance, points, unit)
                if not candidate_issues:
                    chosen_index = index
                    data_issues = []
                    break
                data_issues = candidate_issues
            if data_issues:
                issues.extend(f"{path}: {issue}" for issue in data_issues)
            elif chosen_index is not None:
                chart_sources.append((path, chosen_index))

        elif media.get("kind") == "table":
            rows = media.get("rows") or []
            if not rows:
                issues.append(f"{path}: 表格缺少数据行")
            if not provenance_regions:
                issues.append(f"{path}: 表格缺少可定位的来源区间")
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, list) or not row:
                    continue
                label = str(row[0]).strip()
                if label and not any(label in region for _, region in provenance_regions):
                    issues.append(f"{path}[{row_index}]: 行标签 '{label}' 未出现在任何来源区间")
                for cell in row[1:]:
                    cell_text = str(cell).strip()
                    tokens = number_tokens(cell_text)
                    if not tokens:
                        if cell_text and not any(
                            normalize_text(cell_text) in normalize_text(region)
                            for _, region in provenance_regions
                        ):
                            issues.append(
                                f"{path}[{row_index}]: 单元格 '{cell_text}' 未出现在任何来源区间"
                            )
                        continue
                    for token in tokens:
                        if not any(
                            value_bound_to_label(region, label=label or None, value=token.value)
                            for _, region in provenance_regions
                        ):
                            issues.append(
                                f"{path}[{row_index}]: 表格数值 {token.text} 无法与行标签 '{label}' 绑定"
                            )
            matched_tables = [
                index
                for index, (_, region) in enumerate(provenance_regions)
                if _table_fits(region, rows)
            ]
            if matched_tables:
                table_sources.append((path, matched_tables[0]))

        elif media.get("kind") == "image":
            asset_id = str(media.get("assetId") or "")
            try:
                asset_uuid = UUID(asset_id)
            except ValueError:
                issues.append(f"{path}: image assetId 非法")
                continue
            asset = assets.get(asset_uuid)
            if asset is None:
                issues.append(f"{path}: image assetId 不在本文档资产表中")
                continue
            if asset.kind != "image":
                issues.append(f"{path}: assetId 指向的不是图片资产")
                continue
            asset_ref = _asset_source_ref(asset)
            if asset_ref is None:
                issues.append(f"{path}: 图片资产缺少自身 sourceRef")
            elif provenance_regions and not any(
                _refs_overlap(asset_ref, provenance.source_ref, document_text)
                for provenance, _ in provenance_regions
            ):
                issues.append(f"{path}: 图片资产 sourceRef 与页面 provenance 区间不重叠")

    if len({index for _, index in chart_sources}) != len(chart_sources):
        issues.append("多个图表不得共用同一条 provenance")
    if len({index for _, index in table_sources}) != len(table_sources):
        issues.append("多个表格不得共用同一条 provenance")

    source_value = slide.slots.get("source")
    if isinstance(source_value, str) and source_value.strip():
        source_text = source_value.strip()
        matched_source = False
        for provenance, region in provenance_regions:
            if normalize_text(source_text) in normalize_text(region) or normalize_text(
                source_text
            ) in normalize_text(provenance.quote):
                matched_source = True
                break
            if provenance.original_data is not None and source_text in json.dumps(
                provenance.original_data, ensure_ascii=False
            ):
                matched_source = True
                break
            if re.search(r"[^\d\s.,、]", source_text):
                ref = provenance.source_ref
                line_numbers = {
                    int(token.value)
                    for token in number_tokens(source_text)
                    if token.value == token.value.to_integral_value()
                }
                if any(
                    line in line_numbers for line in range(ref.line_start, ref.line_end + 1)
                ):
                    matched_source = True
                    break
        if not matched_source:
            issues.append("source 插槽与页面 provenance 不匹配（需引用原文片段或对应行号/表号）")

    numbers_slot = slide.slots.get("numbers")
    if isinstance(numbers_slot, list):
        if numbers_slot and not provenance_regions:
            issues.append("关键数字页缺少可定位的来源区间")
        for index, item in enumerate(numbers_slot):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            unit = str(item.get("unit") or "").strip()
            raw_value = str(item.get("value") or "").strip()
            if not raw_value or not provenance_regions:
                continue
            tokens = number_tokens(raw_value)
            if not tokens:
                issues.append(f"numbers[{index}]: 数值 '{raw_value}' 不含数字 token")
                continue
            for token in tokens:
                if not any(
                    value_bound_to_label(
                        region, label=label or None, value=token.value, unit=unit or None
                    )
                    for _, region in provenance_regions
                ):
                    issues.append(
                        f"numbers[{index}]: 数值 {token.text} 无法与标签 '{label}'"
                        f"{(' 和单位 ' + unit) if unit else ''} 在来源区间内绑定"
                    )

        derived_numbers = [
            provenance for provenance, _ in provenance_regions if provenance.type == "derived"
        ]
        for provenance in derived_numbers:
            data = provenance.original_data
            stored_numbers = data.get("numbers") if isinstance(data, dict) else None
            if not isinstance(stored_numbers, list) or not stored_numbers:
                issues.append("关键数字页的 derived originalData 必须包含非空 numbers")
                break
            stored: list[tuple[str, str, str]] = [
                (
                    str(entry.get("label") or "").strip(),
                    str(entry.get("value") or "").strip(),
                    str(entry.get("unit") or "").strip(),
                )
                for entry in stored_numbers
                if isinstance(entry, dict)
            ]
            missing: list[str] = []
            for item in numbers_slot:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                value = str(item.get("value") or "").strip()
                unit = str(item.get("unit") or "").strip()
                if not any(
                    stored_label == label
                    and stored_value == value
                    and (not unit or stored_unit == unit)
                    for stored_label, stored_value, stored_unit in stored
                ):
                    missing.append(f"{label}={value}{unit}")
            if missing:
                issues.append(
                    f"originalData.numbers 与关键数字的 label/value/unit 不一致：{missing}"
                )
                break

    return issues


async def load_assets_for(
    session: AsyncSession, document_id: UUID, asset_ids: set[UUID]
) -> dict[UUID, DocAsset]:
    if not asset_ids:
        return {}
    rows = (
        await session.scalars(
            select(DocAsset).where(DocAsset.document_id == document_id)
        )
    ).all()
    by_id = {row.id: row for row in rows}
    aliases: dict[UUID, DocAsset] = {}
    for row in rows:
        raw = (row.meta or {}).get("aliases")
        if not isinstance(raw, dict):
            continue
        for alias in raw:
            try:
                aliases[UUID(str(alias))] = row
            except (ValueError, TypeError):
                continue
    result: dict[UUID, DocAsset] = {}
    for asset_id in asset_ids:
        resolved: DocAsset | None = by_id.get(asset_id) or aliases.get(asset_id)
        if resolved is not None:
            result[asset_id] = resolved
    return result


def _collect_asset_ids(deck: Deck) -> set[UUID]:
    ids: set[UUID] = set()
    for slide in deck.slides:
        for _, media in _media_entries(slide):
            if media.get("kind") == "image":
                try:
                    ids.add(UUID(str(media.get("assetId"))))
                except (ValueError, TypeError):
                    continue
    return ids


async def deck_semantic_issues(
    session: AsyncSession,
    deck: Deck,
    *,
    document: Document | None,
    require_non_empty: bool = True,
    expected_deck_id: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if deck.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        issues.append(f"不支持的 schemaVersion {deck.schema_version}")
    if expected_deck_id is not None and deck.id != expected_deck_id:
        issues.append("Deck.id 与数据库 Deck 记录不一致")
    if require_non_empty and not deck.slides:
        issues.append("Deck 不能没有 slides")
    try:
        from app.services.theme.manifest import load_manifest

        load_manifest(deck.theme_id)
    except Exception:
        issues.append(f"Theme '{deck.theme_id}' 不存在")

    document_id = document.id if document is not None else deck.meta.source_document_id
    if document_id is None:
        if deck.slides:
            issues.append("Deck 缺少关联文档，无法校验来源")
        return issues

    if deck.meta.source_document_id is not None and deck.meta.source_document_id != document_id:
        issues.append("Deck.meta.sourceDocumentId 与关联文档不一致")

    if document is None:
        document = await session.get(Document, document_id)
    document_text = document.normalized_md if document is not None else None
    if not document_text:
        issues.append("关联文档没有归一化后的 Markdown，无法校验来源")
        return issues

    for index, provenance in enumerate(deck.provenance):
        if provenance.type == "external" and not settings.allow_external_provenance:
            issues.append(f"deck.provenance[{index}]: external provenance 默认关闭")
            continue
        if provenance.document_id != document_id:
            issues.append(f"deck.provenance[{index}]: documentId 与关联文档不一致")
            continue
        _, provenance_issues = _provenance_region(provenance, document_text)
        issues.extend(f"deck.provenance[{index}]: {issue}" for issue in provenance_issues)

    assets = await load_assets_for(session, document_id, _collect_asset_ids(deck))
    for index, slide in enumerate(deck.slides):
        for issue in slide_semantic_issues(
            slide,
            document_id=document_id,
            document_text=document_text,
            assets=assets,
        ):
            issues.append(f"{_slide_issue_prefix(index, slide)}: {issue}")
    return issues


async def ensure_deck_semantics(
    session: AsyncSession,
    deck: Deck,
    *,
    document: Document | None,
    require_non_empty: bool = True,
    expected_deck_id: str | None = None,
) -> None:
    issues = await deck_semantic_issues(
        session,
        deck,
        document=document,
        require_non_empty=require_non_empty,
        expected_deck_id=expected_deck_id,
    )
    if issues:
        raise ValidationFailedError(
            "Deck 语义校验失败（provenance / 数值 / assetId / schema）",
            details={"issues": issues[:40], "total": len(issues)},
        )


def quote_inside_region(quote: str, document_text: str, ref: SourceRef) -> bool:
    region = document_region(document_text, ref)
    if region is None:
        return False
    return quote.strip() in region


def display_check(text: str) -> str:
    return unicodedata.normalize("NFKC", text)
