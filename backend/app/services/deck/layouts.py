import unicodedata
from dataclasses import dataclass, field
from typing import Literal

SlotKind = Literal[
    "short_text",
    "body_text",
    "text_list",
    "image",
    "media",
    "chart",
    "numbers",
    "cards",
    "compare",
    "timeline",
    "steps",
    "source",
    "background",
]


def is_wide(char: str) -> bool:
    return unicodedata.east_asian_width(char) in {"W", "F"}


def display_width(text: str) -> float:
    return sum(1.0 if is_wide(ch) else 0.5 for ch in text)


@dataclass(frozen=True)
class SlotSpec:
    kind: SlotKind
    required: bool = False
    max_chars: float | None = None
    min_items: int | None = None
    max_items: int | None = None
    item_max_chars: float | None = None
    item_secondary_max_chars: float | None = None
    allowed_media: tuple[str, ...] = ()
    item_fields: tuple[str, ...] = ()
    requires_source: bool = False


@dataclass(frozen=True)
class LayoutSpec:
    layout_id: str
    name: str
    summary: str
    when_to_use: str
    slots: dict[str, SlotSpec] = field(default_factory=dict)
    required_provenance: bool = False


LAYOUTS: dict[str, LayoutSpec] = {
    "cover": LayoutSpec(
        layout_id="cover",
        name="封面",
        summary="标题 + 副标题 + 引导语 + 背景",
        when_to_use="整份文稿的第 1 页；章节开篇可用 kicker 标注章节名",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "subtitle": SlotSpec("short_text", max_chars=40),
            "kicker": SlotSpec("short_text", max_chars=12),
            "bg": SlotSpec("background"),
        },
    ),
    "toc": LayoutSpec(
        layout_id="toc",
        name="目录",
        summary="标题 + 3–8 项目录",
        when_to_use="总览全篇结构，或在长文档分节前提示本节内容",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "items": SlotSpec("text_list", True, min_items=3, max_items=8, item_max_chars=16),
        },
    ),
    "bullets": LayoutSpec(
        layout_id="bullets",
        name="要点",
        summary="标题 + 引导句 + 3–7 条要点（可带补充说明）",
        when_to_use="阐述原因、特征、结论等并列信息；最通用的内容页",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "lead": SlotSpec("short_text", max_chars=60),
            "items": SlotSpec(
                "text_list",
                True,
                min_items=3,
                max_items=7,
                item_max_chars=36,
                item_secondary_max_chars=48,
            ),
        },
    ),
    "split-lr": LayoutSpec(
        layout_id="split-lr",
        name="左右分栏",
        summary="标题 + 正文 + 左右分栏媒体",
        when_to_use="需要有图/表/图表与文字并排解释；图宽 ≥ 40% 栏宽",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "body": SlotSpec("body_text", True, max_chars=120),
            "media": SlotSpec("media", True, allowed_media=("image", "chart", "table")),
            "mediaSide": SlotSpec("short_text", max_chars=6),
        },
        required_provenance=True,
    ),
    "split-tb": LayoutSpec(
        layout_id="split-tb",
        name="上下分栏",
        summary="标题 + 正文 + 上下分栏媒体",
        when_to_use="需要一张宽幅图/表支撑一段解释；图高 ≥ 35% 版心",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "body": SlotSpec("body_text", True, max_chars=80),
            "media": SlotSpec("media", True, allowed_media=("image", "chart", "table")),
        },
        required_provenance=True,
    ),
    "cards-3": LayoutSpec(
        layout_id="cards-3",
        name="三卡片",
        summary="标题 + 恰好 3 张卡片",
        when_to_use="三个并列概念、三项支柱、三类场景；不要用于 2 项或 4 项",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "cards": SlotSpec(
                "cards",
                True,
                min_items=3,
                max_items=3,
                item_max_chars=10,
                item_secondary_max_chars=60,
                item_fields=("heading", "text"),
            ),
        },
    ),
    "chart": LayoutSpec(
        layout_id="chart",
        name="图表",
        summary="标题 + 图表 + 图注 + 原文来源",
        when_to_use="原文中有可核对的具体数值，需要可视化对比或趋势",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "chart": SlotSpec("chart", True),
            "caption": SlotSpec("short_text", max_chars=60),
            "source": SlotSpec("source", True),
        },
        required_provenance=True,
    ),
    "big-number": LayoutSpec(
        layout_id="big-number",
        name="关键数字",
        summary="标题 + 1–3 个关键数字 + 注释",
        when_to_use="强调规模、增长率、覆盖率等单个可核对数字",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "numbers": SlotSpec(
                "numbers",
                True,
                min_items=1,
                max_items=3,
                item_max_chars=6,
                item_fields=("value", "label"),
            ),
            "note": SlotSpec("short_text", max_chars=60),
        },
        required_provenance=True,
    ),
    "quote": LayoutSpec(
        layout_id="quote",
        name="引用",
        summary="引文 + 作者 + 原文来源",
        when_to_use="原文中的定义、论断或权威表述，需要逐字呈现",
        slots={
            "quote": SlotSpec("short_text", True, max_chars=80),
            "author": SlotSpec("short_text", max_chars=24),
            "source": SlotSpec("source", True),
        },
        required_provenance=True,
    ),
    "compare": LayoutSpec(
        layout_id="compare",
        name="对比",
        summary="标题 + 左右各 2–5 条对比项",
        when_to_use="方案对比、优劣分析、前后变化",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "left": SlotSpec(
                "compare", True, min_items=2, max_items=5, item_max_chars=28
            ),
            "right": SlotSpec(
                "compare", True, min_items=2, max_items=5, item_max_chars=28
            ),
        },
    ),
    "timeline": LayoutSpec(
        layout_id="timeline",
        name="时间线",
        summary="标题 + 3–6 个时间节点",
        when_to_use="阶段演进、项目排期、历史脉络",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "nodes": SlotSpec(
                "timeline",
                True,
                min_items=3,
                max_items=6,
                item_max_chars=10,
                item_secondary_max_chars=40,
                item_fields=("time", "text"),
            ),
        },
    ),
    "process": LayoutSpec(
        layout_id="process",
        name="流程",
        summary="标题 + 3–5 个步骤",
        when_to_use="方法论步骤、流水线、操作流程；强调先后顺序",
        slots={
            "title": SlotSpec("short_text", True, max_chars=24),
            "steps": SlotSpec(
                "steps",
                True,
                min_items=3,
                max_items=5,
                item_max_chars=12,
                item_secondary_max_chars=40,
                item_fields=("label", "text"),
            ),
        },
    ),
    "full-image": LayoutSpec(
        layout_id="full-image",
        name="全图",
        summary="整版图片 + 图注 + 原文来源",
        when_to_use="原文中的关键截图、照片或整页图表，需要完整呈现",
        slots={
            "media": SlotSpec("image", True, allowed_media=("image",)),
            "caption": SlotSpec("short_text", max_chars=60),
            "source": SlotSpec("source", True),
        },
        required_provenance=True,
    ),
    "ending": LayoutSpec(
        layout_id="ending",
        name="结束页",
        summary="标题 + 一句话 + 联系方式",
        when_to_use="整份文稿最后一页",
        slots={
            "title": SlotSpec("short_text", True, max_chars=16),
            "message": SlotSpec("short_text", max_chars=40),
            "contact": SlotSpec("short_text", max_chars=40),
        },
    ),
}


def layout_catalog_for_prompt() -> str:
    lines: list[str] = []
    for spec in LAYOUTS.values():
        slot_bits = ", ".join(
            f"{name}{'(必填)' if slot.required else ''}" for name, slot in spec.slots.items()
        )
        lines.append(f"- {spec.layout_id}（{spec.name}）：{spec.summary}；插槽：{slot_bits}。适用：{spec.when_to_use}")
    return "\n".join(lines)


def compat_layout_ids() -> tuple[str, ...]:
    return tuple(LAYOUTS.keys())