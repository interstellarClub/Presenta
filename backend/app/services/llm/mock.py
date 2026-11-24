import json
from typing import Any


def _truncate(text: str, limit: float) -> str:
    from app.services.deck.layouts import display_width

    text = " ".join(text.split())
    if display_width(text) <= limit:
        return text
    budget = 0.0
    out: list[str] = []
    for ch in text:
        width = display_width(ch)
        if budget + width > limit:
            break
        budget += width
        out.append(ch)
    return "".join(out).rstrip()


def _sentences(text: str, limit: int = 8) -> list[str]:
    import re

    parts = re.split(r"(?<=[。！？!?；;\.])\s*", " ".join(text.split()))
    cleaned = [p.strip("。；;. ") for p in parts if p.strip("。；;. ")]
    return cleaned[:limit]


def build_outline_payload(context: dict[str, Any]) -> dict[str, Any]:
    sections = context.get("sections") or []
    items: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        title = _truncate(str(section.get("title") or f"第 {index + 1} 节"), 24)
        points = _sentences(str(section.get("summary") or section.get("text") or ""), 5)
        while len(points) < 2:
            points.append(f"要点 {len(points) + 1}")
        items.append(
            {
                "id": f"item-{index + 1}",
                "title": title,
                "points": [_truncate(p, 36) for p in points[:4]],
                "sectionId": section.get("id"),
            }
        )
    return {
        "title": _truncate(str(context.get("documentTitle") or "演示文稿"), 60),
        "items": items,
    }


def build_page_payload(context: dict[str, Any]) -> dict[str, Any]:
    section = context.get("section") or {}
    index = int(section.get("index") or 0)
    total = int(context.get("total") or 0)
    title = _truncate(str(section.get("title") or context.get("documentTitle") or "未命名页面"), 24)
    body = str(section.get("text") or section.get("summary") or "")
    sentences = [_truncate(s, 36) for s in _sentences(body, 6) if s]

    if index == 0:
        return {
            "layout": "cover",
            "slots": {
                "title": title,
                "subtitle": _truncate(str(context.get("documentTitle") or ""), 40),
                "kicker": "PRESENTA",
            },
            "notes": "",
        }
    if index == 1 and total > 4:
        return {
            "layout": "toc",
            "slots": {
                "title": "目录",
                "items": [_truncate(str(i.get("title") or ""), 16) for i in context.get("outlineItems", [])][:8]
                or ["背景与问题", "核心方案", "实施路径"],
            },
            "notes": "",
        }
    if index == total - 1 and total > 2:
        return {
            "layout": "ending",
            "slots": {
                "title": "谢谢",
                "message": _truncate(sentences[0] if sentences else "欢迎交流与指正", 40),
                "contact": "Presenta",
            },
            "notes": "",
        }

    items = sentences[:3] or [title]
    if len(items) == 1:
        items = items * 3
    return {
        "layout": "bullets",
        "slots": {
            "title": title,
            "lead": _truncate(str(section.get("summary") or ""), 60),
            "items": items[:3],
        },
        "notes": "",
    }


def build_intent_payload(context: dict[str, Any]) -> dict[str, Any]:
    operations = list(context.get("candidate_patch") or [])
    if not operations:
        operations = [
            {
                "op": "replace",
                "path": "/motionLevel",
                "value": float(context.get("current_motion_level") or 0.0),
            }
        ]
    return {"operations": operations, "explanation": "mock provider 未执行真实语义编辑"}


def build_payload(purpose: str, context: dict[str, Any]) -> dict[str, Any]:
    if purpose == "outline":
        return build_outline_payload(context)
    if purpose == "page":
        return build_page_payload(context)
    if purpose == "intent":
        return build_intent_payload(context)
    raise ValueError(f"mock provider has no builder for purpose '{purpose}'")


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
