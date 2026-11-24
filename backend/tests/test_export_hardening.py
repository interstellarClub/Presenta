"""导出加固测试：styleOverride 注入防护、slot 样式映射、CSP meta。"""
import io
import uuid

from PIL import Image
from pptx import Presentation

from app.api.schemas.deck import (
    Deck,
    DeckMeta,
    Element,
    ElementLayout,
    Provenance,
    Slide,
    SourceRef,
)
from app.services.export.html import build_standalone_html
from app.services.export.layouts_html import (
    _render_elements,
    _slot_style_rules,
    render_slide_html,
    text_html,
)
from app.services.export.pptx import build_pptx
from app.services.theme.manifest import load_manifest

_DOC_ID = uuid.uuid4()


def _provenance() -> Provenance:
    return Provenance(
        type="derived",
        original_data={"note": "测试图片"},
        documentId=str(_DOC_ID),
        sourceRef=SourceRef(lineStart=1, colStart=0, lineEnd=1, colEnd=10),
        quote="测试图片原文",
    )


def _bullets_slide() -> Slide:
    return Slide(
        layout="bullets",
        slots={"title": "测试标题", "items": ["一", "二", "三"]},
    )


def _full_image_slide(asset_id: str = "asset-xyz") -> Slide:
    return Slide(
        layout="full-image",
        slots={
            "media": {"kind": "image", "assetId": asset_id},
            "source": "原文 P1",
        },
        provenance=[_provenance()],
    )


def test_slot_style_rules_for_layout_null_element() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            style_override={"color": "#1F4E79", "fontSize": 24},
        )
    )
    rules = _slot_style_rules(slide.elements, slide.id)
    assert f'.slide-root[data-slide-id="{slide.id}"] [data-slot="title"]' in rules
    assert "color:#1F4E79" in rules
    assert "font-size:24" in rules


def test_slot_style_rules_maps_layout_elements_to_existing_slot() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            layout=ElementLayout(x=0, y=0, w=12, h=1),
            style_override={"color": "red"},
        )
    )
    rules = _slot_style_rules(slide.elements, slide.id)
    assert "position:absolute" in rules
    assert '[data-slot="title"]' in rules


def test_render_elements_uses_asset_id_from_slots() -> None:
    slide = _full_image_slide()
    slide.elements.append(
        Element(
            type="image",
            slot_path="media",
            layout=ElementLayout(x=0, y=0, w=12, h=1),
        )
    )
    images = {"asset-xyz": "data:image/png;base64,ABC"}
    html = _render_elements(slide, slide.elements, images)
    assert "data:image/png;base64,ABC" in html
    assert 'data-element-id="' in html


def test_render_elements_image_placeholder_when_asset_missing() -> None:
    slide = _full_image_slide(asset_id="missing-asset")
    slide.elements.append(
        Element(
            type="image",
            slot_path="media",
            layout=ElementLayout(x=0, y=0, w=12, h=1),
        )
    )
    html = _render_elements(slide, slide.elements, {})
    assert "图片未内联" in html


def test_render_elements_text_uses_slot_content() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            layout=ElementLayout(x=0, y=0, w=12, h=1),
        )
    )
    html = _render_elements(slide, slide.elements, {})
    assert "测试标题" in html


def test_render_slide_html_injects_slot_style_tag() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            style_override={"color": "#1F4E79"},
        )
    )
    html = render_slide_html(slide)
    assert "<style>" in html
    assert f'.slide-root[data-slide-id="{slide.id}"] [data-slot="title"]' in html


def test_layout_existing_slot_does_not_duplicate_element_overlay() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            layout=ElementLayout(x=1, y=10, w=6, h=20),
        )
    )
    html = render_slide_html(slide)
    assert "position:absolute" in html
    assert '<div class="element-layer">' not in html


def test_render_slide_html_escapes_style_value() -> None:
    slide = _bullets_slide()
    slide.elements.append(
        Element(
            type="text",
            slot_path="title",
            style_override={"color": "red"},
        )
    )
    html = render_slide_html(slide)
    assert "color:red" in html


def test_standalone_html_has_csp_meta() -> None:
    deck = Deck(meta=DeckMeta(title="CSP 测试"), slides=[_bullets_slide()])
    html = build_standalone_html(deck, manifest={"name": "default"}, images={})
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "img-src data:" in html
    assert "style-src 'unsafe-inline'" in html
    assert "script-src 'unsafe-inline'" in html


def test_standalone_html_csp_blocks_external_resources() -> None:
    deck = Deck(meta=DeckMeta(title="CSP 严格"), slides=[_bullets_slide()])
    html = build_standalone_html(deck, manifest={"name": "default"}, images={})
    assert "default-src 'none'" in html
    assert "font-src data:" in html


def test_rich_text_whitelist_renders_without_raw_html() -> None:
    rendered = text_html("**粗体** *斜体* `code` ^2^ <script>x</script>")
    assert "<strong>" in rendered
    assert "<em>" in rendered
    assert "<code>" in rendered
    assert "<sup>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_slot_style_is_scoped_to_one_slide() -> None:
    first = _bullets_slide()
    first.elements.append(
        Element(
            type="text",
            slot_path="title",
            style_override={"color": "red"},
        )
    )
    second = _bullets_slide()
    deck = Deck(meta=DeckMeta(title="隔离"), slides=[first, second])
    html = build_standalone_html(deck, manifest={"name": "default"}, images={})
    assert f'.slide-root[data-slide-id="{first.id}"] [data-slot="title"]' in html
    assert f'.slide-root[data-slide-id="{second.id}"] [data-slot="title"]' not in html


def test_free_chart_element_renders_svg() -> None:
    slide = Slide(
        layout="chart",
        slots={
            "title": "图表",
            "chart": {
                "kind": "chart",
                "type": "bar",
                "series": [{"name": "系列", "points": [{"label": "A", "value": 1}]}],
            },
            "source": "原文 P1",
        },
        provenance=[_provenance()],
    )
    slide.elements.append(
        Element(
            type="chart",
            slot_path="chart",
            layout=ElementLayout(x=0, y=0, w=6, h=40),
        )
    )
    html = _render_elements(slide, slide.elements, {})
    assert "<svg" in html


def test_pptx_uses_rendered_page_snapshot_for_chart() -> None:
    slide = Slide(
        layout="chart",
        slots={
            "title": "图表",
            "chart": {
                "kind": "chart",
                "type": "bar",
                "series": [{"name": "系列", "points": [{"label": "A", "value": 1}]}],
            },
            "source": "原文 P1",
        },
        provenance=[_provenance()],
    )
    deck = Deck(meta=DeckMeta(title="PPT"), slides=[slide])
    image = io.BytesIO()
    Image.new("RGB", (16, 9), (20, 40, 80)).save(image, format="PNG")
    data, _ = build_pptx(
        deck=deck,
        manifest=load_manifest("academic"),
        images={},
        slides_html=["<div></div>"],
        options={},
        rendered_pages={0: image.getvalue()},
    )
    prs = Presentation(io.BytesIO(data))
    pictures = [
        shape for shape in prs.slides[0].shapes if shape.shape_type == 13
    ]
    assert pictures
