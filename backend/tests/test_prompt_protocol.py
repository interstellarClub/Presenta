import json
import uuid

import pytest
from pydantic import SecretStr, ValidationError

from app.api.schemas.deck import Provenance, SourceRef
from app.api.schemas.outline import Outline, OutlineItem
from app.api.schemas.pages import PageDraft, draft_to_slide
from app.db.models import Document
from app.services.deck.layouts import layout_catalog_for_prompt
from app.services.llm import gateway
from app.services.llm.prompts import load_prompt, render
from app.services.pages.generator import _page_prompt


def _provenance() -> Provenance:
    return Provenance(
        type="original",
        document_id=uuid.uuid4(),
        source_ref=SourceRef(line_start=3, col_start=0, line_end=3, col_end=18),
        quote="原文逐字片段",
    )


def test_page_draft_accepts_optional_provenance() -> None:
    draft = PageDraft(
        layout="bullets",
        slots={"title": "标题", "items": ["一", "二", "三"]},
        provenance=[_provenance()],
    )
    slide = draft_to_slide(draft)
    assert slide.layout == "bullets"
    assert len(slide.provenance) == 1
    assert slide.provenance[0].quote == "原文逐字片段"


def test_page_draft_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PageDraft(layout="bullets", slots={}, unknownField=1)


def test_prompts_render_all_placeholders() -> None:
    system_prompt = render(load_prompt("pages", "page"), layout_catalog=layout_catalog_for_prompt())
    assert "{layout_catalog}" not in system_prompt
    assert "不要输出 provenance" in system_prompt

    document = Document(id=uuid.uuid4(), title="协议文档", source_type="editor_md")
    outline = Outline(
        title="协议演示",
        subtitle="",
        items=[OutlineItem(id="item-1", title="页面", points=["要点"], section_id="sec-001")],
    )
    system_prompt, user_prompt = _page_prompt(
        document=document,
        outline=outline,
        item_index=0,
        item_title="页面",
        points=["要点"],
        section={"id": "sec-001", "lineStart": 3, "lineEnd": 3, "text": "原文逐字片段"},
        allowed_layouts=["bullets"],
        assets=[],
    )
    for placeholder in (
        "{document_title}",
        "{page_index}",
        "{page_total}",
        "{item_title}",
        "{points}",
        "{section_id}",
        "{source_ref}",
        "{allowed_layouts}",
        "{document_id}",
        "{section_text}",
        "{assets}",
    ):
        assert placeholder not in user_prompt, placeholder
    assert "不要输出 provenance" in user_prompt
    assert "不要输出 provenance" in system_prompt


def test_repair_prompt_contains_previous_json_and_errors() -> None:
    rendered = render(
        load_prompt("pages", "repair"),
        errors="图表数值 99.0 无法绑定",
        previous_json='{"layout":"chart"}',
    )
    assert "图表数值 99.0" in rendered
    assert '{"layout":"chart"}' in rendered
    assert "不要自行编造 provenance" in rendered
    assert "{errors}" not in rendered
    assert "{previous_json}" not in rendered


def test_schema_repair_prompt_exists_and_renders() -> None:
    rendered = render(load_prompt("llm", "schema_repair"), errors="bad json")
    assert "bad json" in rendered
    assert "{errors}" not in rendered


async def test_deepseek_page_payload_with_provenance_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "layout": "bullets",
        "slots": {"title": "标题", "items": ["一", "二", "三"]},
        "notes": "",
        "provenance": [_provenance().model_dump(mode="json", by_alias=True)],
    }

    async def fake_post(
        messages: list[dict[str, str]], *, thinking: bool, temperature: float
    ) -> tuple[str, dict[str, int]]:
        return json.dumps(payload, ensure_ascii=False), {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(gateway, "_post_deepseek", fake_post)
    monkeypatch.setattr(gateway.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(
        gateway.settings,
        "deepseek_api_key",
        SecretStr("test-key-for-unit-test-1234567890"),
    )

    from app.db.session import SessionFactory, ensure_schema

    await ensure_schema()
    async with SessionFactory() as session:
        result = await gateway.generate_structured(
            session,
            purpose="page",
            schema=PageDraft,
            system_prompt="system",
            user_prompt="user",
            mock_context={},
            repair_budget=0,
        )
    assert isinstance(result, PageDraft)
    assert result.provenance and result.provenance[0].quote == "原文逐字片段"
