"""v1 Deck snapshot 迁移测试：验证 migrate_deck_payload 把 v1 original provenance 迁移为 v2 derived。"""

from app.services.deck.semantics import migrate_deck_payload


def test_v1_chart_provenance_migrated_to_derived() -> None:
    v1_payload = {
        "schemaVersion": 1,
        "id": "test",
        "meta": {"title": "测试"},
        "themeId": "academic",
        "slides": [
            {
                "id": "slide1",
                "layout": "chart",
                "slots": {
                    "title": "图表页",
                    "chart": {
                        "kind": "chart",
                        "series": [
                            {"name": "系列1", "points": [{"label": "A", "value": 10}]}
                        ],
                        "unit": "",
                    },
                },
                "provenance": [
                    {
                        "type": "original",
                        "documentId": "doc1",
                        "sourceRef": {
                            "lineStart": 1,
                            "colStart": 0,
                            "lineEnd": 1,
                            "colEnd": 10,
                        },
                        "quote": "原始数据",
                    }
                ],
            }
        ],
    }
    result = migrate_deck_payload(v1_payload)
    assert result["schemaVersion"] == 2
    slide = result["slides"][0]
    assert slide["provenance"][0]["type"] == "derived"
    assert "originalData" in slide["provenance"][0]
    assert slide["provenance"][0]["originalData"]["columns"] == ["label", "value"]
    assert slide["provenance"][0]["originalData"]["rows"] == [["A", 10]]


def test_v1_numbers_provenance_migrated_to_derived() -> None:
    v1_payload = {
        "schemaVersion": 1,
        "id": "test",
        "meta": {"title": "测试"},
        "themeId": "academic",
        "slides": [
            {
                "id": "slide1",
                "layout": "numbers",
                "slots": {
                    "title": "关键数字",
                    "numbers": [{"label": "指标", "value": "42", "unit": "%"}],
                },
                "provenance": [
                    {
                        "type": "original",
                        "documentId": "doc1",
                        "sourceRef": {
                            "lineStart": 1,
                            "colStart": 0,
                            "lineEnd": 1,
                            "colEnd": 10,
                        },
                        "quote": "指标 42%",
                    }
                ],
            }
        ],
    }
    result = migrate_deck_payload(v1_payload)
    assert result["schemaVersion"] == 2
    slide = result["slides"][0]
    assert slide["provenance"][0]["type"] == "derived"
    assert "originalData" in slide["provenance"][0]
    assert slide["provenance"][0]["originalData"]["numbers"] == [
        {"label": "指标", "value": "42", "unit": "%"}
    ]


def test_v2_payload_not_modified() -> None:
    v2_payload = {
        "schemaVersion": 2,
        "id": "test",
        "meta": {"title": "测试"},
        "themeId": "academic",
        "slides": [],
    }
    result = migrate_deck_payload(v2_payload)
    assert result is v2_payload


def test_v1_payload_not_mutated() -> None:
    v1_payload = {
        "schemaVersion": 1,
        "id": "test",
        "meta": {"title": "测试"},
        "themeId": "academic",
        "slides": [
            {
                "id": "slide1",
                "layout": "chart",
                "slots": {
                    "chart": {
                        "kind": "chart",
                        "series": [
                            {"name": "s", "points": [{"label": "A", "value": 1}]}
                        ],
                        "unit": "",
                    },
                },
                "provenance": [
                    {
                        "type": "original",
                        "documentId": "d",
                        "sourceRef": {
                            "lineStart": 1,
                            "colStart": 0,
                            "lineEnd": 1,
                            "colEnd": 1,
                        },
                        "quote": "q",
                    }
                ],
            }
        ],
    }
    result = migrate_deck_payload(v1_payload)
    assert v1_payload["schemaVersion"] == 1
    assert v1_payload["slides"][0]["provenance"][0]["type"] == "original"
    assert result["schemaVersion"] == 2


def test_v1_image_provenance_preserved() -> None:
    v1_payload = {
        "schemaVersion": 1,
        "id": "test",
        "meta": {"title": "测试"},
        "themeId": "academic",
        "slides": [
            {
                "id": "slide1",
                "layout": "image",
                "slots": {
                    "image": {"kind": "image", "assetId": "0" * 32},
                },
                "provenance": [
                    {
                        "type": "original",
                        "documentId": "doc1",
                        "sourceRef": {
                            "lineStart": 1,
                            "colStart": 0,
                            "lineEnd": 1,
                            "colEnd": 5,
                        },
                        "quote": "图片",
                    }
                ],
            }
        ],
    }
    result = migrate_deck_payload(v1_payload)
    assert result["schemaVersion"] == 2
    slide = result["slides"][0]
    assert slide["provenance"][0]["type"] == "original"