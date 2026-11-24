import uuid

import pytest
from pydantic import ValidationError

from app.api.schemas.deck import Deck, DeckMeta, Provenance, Slide, SourceRef
from app.core.errors import ValidationFailedError
from app.services.deck.versioning import validate_operations
from app.services.pages.validator import validate_quotes_and_numbers

DOC_ID = uuid.uuid4()
SOURCE_QUOTE = "原文第 3 页表 1：2023 年收入 12.4 亿元，同比增长 8.5%。"
SOURCE_TEXT = "第一行\n第二行\n" + SOURCE_QUOTE


def _provenance(quote: str = SOURCE_QUOTE) -> Provenance:
    return Provenance(
        type="derived",
        original_data={"columns": ["label", "value"], "rows": [["2023", 12.4]]},
        documentId=str(DOC_ID),
        sourceRef=SourceRef(lineStart=3, colStart=0, lineEnd=3, colEnd=len(SOURCE_QUOTE)),
        quote=quote,
    )


def test_valid_bullets_slide_passes() -> None:
    slide = Slide(
        layout="bullets",
        slots={
            "title": "三个关键结论",
            "lead": "来自原文的总结",
            "items": ["结论一", "结论二", "结论三"],
        },
    )
    assert slide.layout == "bullets"


def test_unknown_slot_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Slide(layout="bullets", slots={"title": "标题", "items": ["一", "二", "三"], "extra": "x"})


def test_image_slot_rejects_urls() -> None:
    with pytest.raises(ValidationError):
        Slide(
            layout="full-image",
            slots={
                "media": {"kind": "image", "assetId": "https://example.com/x.png"},
                "source": "原文 P1",
            },
            provenance=[_provenance()],
        )


def test_title_length_limit_uses_display_width() -> None:
    with pytest.raises(ValidationError):
        Slide(layout="bullets", slots={"title": "标" * 25, "items": ["一", "二", "三"]})


def test_chart_layout_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        Slide(
            layout="chart",
            slots={
                "title": "收入趋势",
                "chart": {
                    "kind": "chart",
                    "type": "bar",
                    "series": [
                        {"name": "收入", "points": [{"label": "2023", "value": 12.4}]}
                    ],
                },
                "source": "原文 P3 表1",
            },
        )


def test_chart_value_must_match_quote() -> None:
    slide = Slide(
        layout="chart",
        slots={
            "title": "收入趋势",
            "chart": {
                "kind": "chart",
                "type": "bar",
                "series": [
                    {"name": "收入", "points": [{"label": "2023", "value": 12.4}]}
                ],
            },
            "caption": "2023 年收入",
            "source": "原文 P3 表1",
        },
        provenance=[_provenance()],
    )
    assert validate_quotes_and_numbers(slide, SOURCE_TEXT) == []

    forged = slide.model_copy(deep=True)
    forged.slots["chart"]["series"][0]["points"][0]["value"] = 99.9
    issues = validate_quotes_and_numbers(forged, SOURCE_TEXT)
    assert any("99.9" in issue for issue in issues)


def test_quote_must_be_verbatim() -> None:
    slide = Slide(
        layout="quote",
        slots={"quote": "原文引用内容", "author": "作者", "source": "原文 P2"},
        provenance=[_provenance(quote="这句原文里没有")],
    )
    issues = validate_quotes_and_numbers(slide, SOURCE_TEXT)
    assert any("引用文本" in issue for issue in issues)


def test_deck_hash_and_meta() -> None:
    deck = Deck(meta=DeckMeta(title="测试文稿"), slides=[])
    payload = deck.model_dump(mode="json", by_alias=True)
    assert payload["meta"]["title"] == "测试文稿"
    assert "sourceDocumentId" in payload["meta"]


def test_patch_rejects_layout_and_id_mutation() -> None:
    with pytest.raises(ValidationFailedError):
        validate_operations([{"op": "replace", "path": "/slides/0/layout", "value": "cover"}])
    with pytest.raises(ValidationFailedError):
        validate_operations([{"op": "replace", "path": "/slides/0/id", "value": "x"}])
    validate_operations([{"op": "replace", "path": "/motionLevel", "value": 0.4}])

def test_style_override_rejects_quote_injection() -> None:
    from app.api.schemas.deck import Element

    with pytest.raises(ValidationError):
        Element(
            type="text",
            slot_path="title",
            style_override={"color": 'red"><img src=x onerror=alert(1)>'},
        )


def test_style_override_rejects_url_function() -> None:
    from app.api.schemas.deck import Element

    with pytest.raises(ValidationError):
        Element(
            type="text",
            slot_path="title",
            style_override={"background": "url(javascript:alert(1))"},
        )


def test_style_override_rejects_semicolon_injection() -> None:
    from app.api.schemas.deck import Element

    with pytest.raises(ValidationError):
        Element(
            type="text",
            slot_path="title",
            style_override={"color": "red;position:fixed"},
        )


def test_style_override_rejects_unknown_key() -> None:
    from app.api.schemas.deck import Element

    with pytest.raises(ValidationError):
        Element(
            type="text",
            slot_path="title",
            style_override={"evil": "red"},
        )


def test_style_override_accepts_safe_value() -> None:
    from app.api.schemas.deck import Element

    element = Element(
        type="text",
        slot_path="title",
        style_override={"color": "#1F4E79", "fontSize": 24, "fontWeight": "bold"},
    )
    assert element.style_override["color"] == "#1F4E79"