import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.schemas.deck import Deck, DeckMeta, Provenance, Slide, SourceRef
from app.core.errors import ValidationFailedError
from app.core.security import token_digest
from app.db.models import AuditLog, Document, ShareToken, User
from app.db.models import Deck as DeckRow
from app.db.session import SessionFactory
from app.services.deck.semantics import (
    bounded_value_present,
    slide_semantic_issues,
    value_bound_to_label,
)
from app.services.deck.versioning import (
    commit_deck_change,
    create_version,
    load_current_deck,
    load_deck_at,
    rollback_to,
)
from app.services.ingest.markdown import build_ast

SOURCE_LINE = "2021 年 A 产品收入 12.4 亿元。"
DOCUMENT_TEXT = f"# 数据\n\n{SOURCE_LINE}\n"


def _chart_slide(*, label: str = "A 产品", value: float = 12.4, unit: str = "亿元") -> Slide:
    return Slide(
        layout="chart",
        slots={
            "title": "收入结构",
            "chart": {
                "kind": "chart",
                "type": "bar",
                "series": [
                    {"name": "收入", "points": [{"label": label, "value": value}]}
                ],
                "unit": unit,
            },
            "caption": "A 产品收入",
            "source": "原文 L3",
        },
        provenance=[
            Provenance(
                type="derived",
                document_id=uuid.uuid4(),
                source_ref=SourceRef(
                    line_start=3, col_start=0, line_end=3, col_end=len(SOURCE_LINE)
                ),
                quote=SOURCE_LINE,
                original_data={"columns": ["label", "value"], "rows": [[label, value]]},
            )
        ],
    )


def test_bounded_number_matching_rejects_prefix_matches() -> None:
    text = "2021 年营收 12.4 亿元，增长 8.5%。"
    assert bounded_value_present(text, 12.4)
    assert bounded_value_present(text, 2021)
    assert not bounded_value_present(text, 12)
    assert not bounded_value_present(text, 1)
    assert not bounded_value_present(text, 2)
    assert not bounded_value_present("编号 2021 号", 1)
    assert bounded_value_present("完成率 42%（同比 +3.1%）", 42)
    assert bounded_value_present("收入 1,234.5 万元", 1234.5)


def test_value_must_bind_to_its_own_label() -> None:
    region = "A 组收入 100 万元；B 组收入 200 万元。"
    assert value_bound_to_label(region, label="A 组", value=100)
    assert not value_bound_to_label(region, label="A 组", value=200)
    assert value_bound_to_label(region, label="B 组", value=200)
    assert not value_bound_to_label(region, label="C 组", value=100)

    comma_region = "A 组收入 100 万元，B 组收入 200 万元。"
    assert value_bound_to_label(comma_region, label="A 组", value=100)
    assert not value_bound_to_label(comma_region, label="A 组", value=200)
    assert value_bound_to_label(comma_region, label="B 组", value=200)
    assert not value_bound_to_label(comma_region, label="B 组", value=100)

    colon_region = "甲指标：10；乙指标：20"
    assert value_bound_to_label(colon_region, label="甲指标", value=10)
    assert not value_bound_to_label(colon_region, label="甲指标", value=20)

    multi_metric = "甲指标 10/20/30"
    assert value_bound_to_label(multi_metric, label="甲指标", value=10)
    assert not value_bound_to_label(multi_metric, label="甲指标", value=20)
    assert not value_bound_to_label(multi_metric, label="甲指标", value=30)

    parenthesised = "收入（12.4 亿元），增长（8.5%）"
    assert value_bound_to_label(parenthesised, label="收入", value=12.4, unit="亿元")
    assert not value_bound_to_label(parenthesised, label="收入", value=8.5)


def test_slide_semantics_detect_provenance_mismatch_and_forged_value() -> None:
    document_id = uuid.uuid4()
    valid = _chart_slide()
    valid.provenance[0].document_id = document_id
    assert slide_semantic_issues(
        valid, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    ) == []

    wrong_doc = _chart_slide()
    wrong_doc.provenance[0].document_id = uuid.uuid4()
    assert any(
        "documentId" in issue
        for issue in slide_semantic_issues(
            wrong_doc, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
        )
    )

    forged = _chart_slide(value=99.0)
    forged.provenance[0].document_id = document_id
    issues = slide_semantic_issues(
        forged, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("99.0" in issue for issue in issues)

    wrong_label = _chart_slide(label="B 产品")
    wrong_label.provenance[0].document_id = document_id
    issues = slide_semantic_issues(
        wrong_label, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("B 产品" in issue for issue in issues)


def test_slide_semantics_reject_bad_source_ref_and_quote() -> None:
    document_id = uuid.uuid4()
    bad_ref = _chart_slide()
    bad_ref.provenance[0].document_id = document_id
    bad_ref.provenance[0].source_ref = SourceRef(
        line_start=99, col_start=0, line_end=99, col_end=10
    )
    assert any(
        "sourceRef" in issue
        for issue in slide_semantic_issues(
            bad_ref, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
        )
    )

    narrow_columns = _chart_slide()
    narrow_columns.provenance[0].document_id = document_id
    narrow_columns.provenance[0].source_ref = SourceRef(
        line_start=3, col_start=0, line_end=3, col_end=2
    )
    assert any(
        "quote" in issue
        for issue in slide_semantic_issues(
            narrow_columns, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
        )
    )

    bad_quote = _chart_slide()
    bad_quote.provenance[0].document_id = document_id
    bad_quote.provenance[0].quote = "这段原文里没有"
    assert any(
        "quote" in issue
        for issue in slide_semantic_issues(
            bad_quote, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
        )
    )


async def _deck_with_slides(client: AsyncClient, invited_user: dict) -> str:
    created = await client.post(
        "/api/documents/editor",
        json={
            "title": "语义测试",
            "markdown": (
                "# 背景\n\n这里是一段用于生成演示文稿的正文。\n\n"
                "# 方案\n\n采用结构化 Schema。\n\n"
                "# 结论\n\n全部数据必须可溯源。\n"
            ),
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]
    for _ in range(100):
        detail = (await client.get(f"/api/documents/{document_id}")).json()
        if detail["status"] in {"ready", "failed"}:
            break
        await __import__("asyncio").sleep(0.05)
    assert detail["status"] == "ready"
    items = [
        {
            "id": f"item-{index + 1}",
            "title": section["title"],
            "points": [section["preview"][:36] or section["title"]],
            "sectionId": section["id"],
        }
        for index, section in enumerate(detail["sections"])
    ]
    outline = {"title": "语义演示", "subtitle": "", "items": items}
    assert (
        await client.post(f"/api/documents/{document_id}/outline/confirm", json=outline)
    ).status_code == 200
    deck = await client.post("/api/decks", json={"documentId": document_id, "outline": outline})
    assert deck.status_code == 201, deck.text
    deck_id = deck.json()["deck"]["id"]
    generated = await client.post(f"/api/decks/{deck_id}/generate")
    assert generated.status_code == 202
    for _ in range(400):
        job = (await client.get(f"/api/jobs/{generated.json()['jobId']}")).json()
        if job["status"] in {"succeeded", "partial", "failed", "cancelled"}:
            break
        await __import__("asyncio").sleep(0.05)
    assert job["status"] in {"succeeded", "partial"}, job
    return deck_id


@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "replace", "path": "/id", "value": "x"}],
        [{"op": "replace", "path": "/schemaVersion", "value": 2}],
        [{"op": "replace", "path": "/slides/0/id", "value": "x"}],
        [{"op": "replace", "path": "/slides/0/layout", "value": "cover"}],
        [{"op": "remove", "path": "/slides/0"}],
        [{"op": "replace", "path": "/slides", "value": []}],
        [{"op": "add", "path": "/slides/-", "value": {}}],
        [{"op": "replace", "path": "/meta/sourceDocumentId", "value": None}],
    ],
)
async def test_patch_read_only_and_slide_structure_are_rejected(
    client: AsyncClient, invited_user: dict, operations: list[dict]
) -> None:
    deck_id = await _deck_with_slides(client, invited_user)
    response = await client.patch(
        f"/api/decks/{deck_id}", json={"operations": operations}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_failed"


def test_chart_requires_derived_provenance_with_original_data() -> None:
    document_id = uuid.uuid4()
    slide = _chart_slide()
    slide.provenance[0].document_id = document_id
    slide.provenance[0] = Provenance(
        type="original",
        document_id=document_id,
        source_ref=slide.provenance[0].source_ref,
        quote=SOURCE_LINE,
    )
    issues = slide_semantic_issues(
        slide, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("derived" in issue for issue in issues)


async def test_patch_rejects_unknown_theme(client: AsyncClient, invited_user: dict) -> None:
    deck_id = await _deck_with_slides(client, invited_user)
    response = await client.patch(
        f"/api/decks/{deck_id}",
        json={"operations": [{"op": "replace", "path": "/themeId", "value": "no-such-theme"}]},
    )
    assert response.status_code == 422, response.text


async def test_intent_returns_validated_patch_preview(
    client: AsyncClient, invited_user: dict
) -> None:
    deck_id = await _deck_with_slides(client, invited_user)
    current = await client.get(f"/api/decks/{deck_id}")
    response = await client.post(
        f"/api/decks/{deck_id}/intent",
        json={
            "instruction": "把整体动效调低一点",
            "expectedSeq": current.json()["versionSeq"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operations"]
    assert payload["preview"]["id"] == current.json()["deck"]["id"]


async def test_patch_forged_chart_value_is_rejected(
    client: AsyncClient, invited_user: dict
) -> None:
    async with SessionFactory() as session:
        user = await session.scalar(select(User).limit(1))
        document = Document(
            user_id=user.id,
            title="图表来源",
            source_type="editor_md",
            normalized_md=DOCUMENT_TEXT,
            ast=build_ast(DOCUMENT_TEXT),
            status="ready",
        )
        session.add(document)
        await session.flush()

        from app.db.models import Deck as DeckRow

        deck_row = DeckRow(
            user_id=user.id,
            document_id=document.id,
            title="图表 Deck",
            theme_id="academic",
        )
        session.add(deck_row)
        await session.flush()

        slide = _chart_slide()
        slide.provenance[0].document_id = document.id
        deck = Deck(
            id=deck_row.id.hex,
            theme_id="academic",
            meta=DeckMeta(title="图表 Deck", source_document_id=document.id),
            slides=[slide],
        )
        await create_version(
            session,
            deck_row,
            snapshot=deck.model_dump(mode="json", by_alias=True),
            kind="anchor",
            document=document,
        )
        with pytest.raises(ValidationFailedError):
            await commit_deck_change(
                session,
                deck_row,
                [
                    {
                        "op": "replace",
                        "path": "/slides/0/slots/chart/series/0/points/0/value",
                        "value": 99,
                    }
                ],
                document=document,
            )


async def test_failed_login_audit_survives_rollback(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login",
        json={
            "email": f"missing-{uuid.uuid4().hex[:8]}@example.com",
            "password": "wrong-pass-1",
        },
    )
    assert response.status_code == 401
    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "auth.login_failed")
            )
        ).all()
    assert rows, "failed login audit must be persisted outside the request transaction"


async def test_share_tokens_are_random_hash_only(
    client: AsyncClient, invited_user: dict
) -> None:
    deck_id = await _deck_with_slides(client, invited_user)
    created = await client.post(
        "/api/shares",
        json={
            "deckId": deck_id,
            "password": "share-secret-123",
            "ttlHours": 2,
            "allowDownload": True,
            "formats": ["html"],
        },
    )
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]

    first = await client.post(
        f"/api/shares/guest/{slug}/unlock", json={"password": "share-secret-123"}
    )
    assert first.status_code == 200
    first_cookie = first.cookies.get(f"presenta_share_{slug}")
    second = await client.post(
        f"/api/shares/guest/{slug}/unlock", json={"password": "share-secret-123"}
    )
    assert second.status_code == 200
    second_cookie = second.cookies.get(f"presenta_share_{slug}")
    assert first_cookie and second_cookie and first_cookie != second_cookie

    async with SessionFactory() as session:
        tokens = (
            await session.scalars(
                select(ShareToken).where(
                    ShareToken.token_hash.in_(
                        [token_digest(first_cookie), token_digest(second_cookie)]
                    )
                )
            )
        ).all()
    assert len(tokens) == 2
    assert all(token.token_hash != first_cookie for token in tokens)


async def test_share_accepts_client_mp4_and_rejects_weak_password(
    client: AsyncClient, invited_user: dict
) -> None:
    deck_id = await _deck_with_slides(client, invited_user)
    mp4 = await client.post(
        "/api/shares",
        json={
            "deckId": deck_id,
            "password": "share-secret-123",
            "ttlHours": 2,
            "allowDownload": True,
            "formats": ["mp4"],
        },
    )
    assert mp4.status_code == 201
    assert "mp4" in mp4.json()["downloadFormats"]

    weak = await client.post(
        "/api/shares",
        json={
            "deckId": deck_id,
            "password": "1234",
            "ttlHours": 2,
            "allowDownload": True,
            "formats": ["html"],
        },
    )
    assert weak.status_code == 422

def _element(element_id: str) -> dict:
    return {
        "id": element_id,
        "type": "text",
        "slotPath": element_id,
        "styleOverride": {},
        "anim": [],
        "layout": None,
        "component": None,
        "provenance": None,
    }


async def test_rollback_then_edit_does_not_reintroduce_abandoned_branch() -> None:
    async with SessionFactory() as session:
        user = await session.scalar(select(User).limit(1))
        document = Document(
            user_id=user.id,
            title="分支测试",
            source_type="editor_md",
            normalized_md=DOCUMENT_TEXT,
            ast=build_ast(DOCUMENT_TEXT),
            status="ready",
        )
        session.add(document)
        await session.flush()
        deck_row = DeckRow(
            user_id=user.id,
            document_id=document.id,
            title="分支测试",
            theme_id="academic",
        )
        session.add(deck_row)
        await session.flush()

        slide = Slide(
            layout="bullets",
            slots={"title": "要点", "items": ["一", "二", "三"]},
        )
        deck = Deck(
            id=deck_row.id.hex,
            theme_id="academic",
            meta=DeckMeta(title="分支测试", source_document_id=document.id),
            slides=[slide],
        )
        await create_version(
            session,
            deck_row,
            snapshot=deck.model_dump(mode="json", by_alias=True),
            kind="anchor",
            document=document,
        )
        await session.commit()

        await commit_deck_change(
            session,
            deck_row,
            [{"op": "add", "path": "/slides/0/elements/-", "value": _element("old")}],
            document=document,
        )
        abandoned_seq = deck_row.current_version_seq
        await session.commit()

        assert await rollback_to(session, deck_row, 1, document=document) == 1
        await session.commit()

        await commit_deck_change(
            session,
            deck_row,
            [{"op": "add", "path": "/slides/0/elements/-", "value": _element("new")}],
            document=document,
        )
        await session.commit()

        current = await load_current_deck(session, deck_row)
        assert [element.id for element in current.slides[0].elements] == ["new"]

        abandoned = Deck.model_validate(
            await load_deck_at(session, deck_row.id, abandoned_seq)
        )
        assert [element.id for element in abandoned.slides[0].elements] == ["old"]


async def test_rollback_to_empty_deck_is_rejected() -> None:
    from app.core.errors import ConflictError

    async with SessionFactory() as session:
        user = await session.scalar(select(User).limit(1))
        document = Document(
            user_id=user.id,
            title="空回退",
            source_type="editor_md",
            normalized_md=DOCUMENT_TEXT,
            ast=build_ast(DOCUMENT_TEXT),
            status="ready",
        )
        session.add(document)
        await session.flush()
        deck_row = DeckRow(
            user_id=user.id,
            document_id=document.id,
            title="空回退",
            theme_id="academic",
        )
        session.add(deck_row)
        await session.flush()

        empty = Deck(
            id=deck_row.id.hex,
            theme_id="academic",
            meta=DeckMeta(title="空回退", source_document_id=document.id),
        )
        await create_version(
            session,
            deck_row,
            snapshot=empty.model_dump(mode="json", by_alias=True),
            kind="anchor",
            document=document,
        )
        filled = empty.model_copy(deep=True)
        filled.slides = [
            Slide(layout="bullets", slots={"title": "要点", "items": ["一", "二", "三"]})
        ]
        await create_version(
            session,
            deck_row,
            snapshot=filled.model_dump(mode="json", by_alias=True),
            kind="milestone",
            document=document,
        )
        with pytest.raises(ConflictError):
            await rollback_to(session, deck_row, 1, document=document)


def test_source_slot_must_match_provenance() -> None:
    document_id = uuid.uuid4()
    slide = _chart_slide()
    slide.provenance[0].document_id = document_id
    slide.slots["source"] = "完全无关的出处"
    issues = slide_semantic_issues(
        slide, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("source 插槽" in issue for issue in issues)


def test_derived_original_data_must_not_be_empty() -> None:
    document_id = uuid.uuid4()
    slide = _chart_slide()
    slide.provenance[0].document_id = document_id
    slide.provenance[0].original_data = {}
    issues = slide_semantic_issues(
        slide, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("originalData" in issue for issue in issues)


def test_derived_original_data_must_match_chart_points() -> None:
    document_id = uuid.uuid4()
    slide = _chart_slide()
    slide.provenance[0].document_id = document_id
    slide.provenance[0].original_data = {
        "columns": ["label", "value"],
        "rows": [["A 产品", 1.0]],
        "unit": "亿元",
    }
    issues = slide_semantic_issues(
        slide, document_id=document_id, document_text=DOCUMENT_TEXT, assets={}
    )
    assert any("originalData" in issue for issue in issues)


def test_image_source_ref_must_overlap_by_columns_not_only_lines() -> None:
    from app.db.models import DocAsset

    document_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    quote = SOURCE_LINE[10:]
    provenance = Provenance(
        type="original",
        document_id=document_id,
        source_ref=SourceRef(
            line_start=3, col_start=10, line_end=3, col_end=len(SOURCE_LINE)
        ),
        quote=quote,
    )
    slide = Slide(
        layout="full-image",
        slots={
            "media": {"kind": "image", "assetId": asset_id.hex, "alt": "图"},
            "caption": "图",
            "source": "原文 L3",
        },
        provenance=[provenance],
    )
    asset = DocAsset(
        id=asset_id,
        document_id=document_id,
        kind="image",
        sha256="x",
        source_ref={"lineStart": 3, "colStart": 0, "lineEnd": 3, "colEnd": 2},
    )
    issues = slide_semantic_issues(
        slide, document_id=document_id, document_text=DOCUMENT_TEXT, assets={asset_id: asset}
    )
    assert any("不重叠" in issue for issue in issues)
