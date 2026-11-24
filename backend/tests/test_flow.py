import json

from httpx import AsyncClient

from tests.conftest import wait_job

MARKDOWN = """# 项目背景

团队需要把论文与报告转成能在会上讲的演示文稿，过去一份 40 页文档要花半天重排结构。

# 核心方案

系统以结构化 Schema 为唯一真相，AI 只输出「版式 ID + 插槽内容」，编辑改 Schema 而不是改 HTML。

# 实施路径

第一阶段完成文档解析、大纲确认与逐页生成；第二阶段补齐就地编辑与版本历史；第三阶段打通导出与分享。
"""


async def _sse_events(client: AsyncClient, url: str) -> list[dict]:
    events: list[dict] = []
    current_event = "message"
    async with client.stream("POST", url) as response:
        assert response.status_code == 200, await response.aread()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                events.append({"event": current_event, "data": payload})
    return events


async def test_full_m1_flow(client: AsyncClient, invited_user: dict) -> None:
    created = await client.post(
        "/api/documents/editor",
        json={"title": "Presenta 测试文档", "markdown": MARKDOWN},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]
    job_id = created.json()["jobId"]

    ingest_job = await wait_job(client, job_id)
    assert ingest_job["status"] == "succeeded", ingest_job
    assert ingest_job["result"]["sections"] == 3

    detail = await client.get(f"/api/documents/{document_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "ready"
    assert body["sectionCount"] == 3
    assert body["normalizedMd"].startswith("# 项目背景")
    assert {section["title"] for section in body["sections"]} == {
        "项目背景",
        "核心方案",
        "实施路径",
    }

    events = await _sse_events(client, f"/api/documents/{document_id}/outline")
    kinds = [event["event"] for event in events]
    assert "stage" in kinds
    assert "done" in kinds
    items = [event["data"] for event in events if event["event"] == "item"]
    assert len(items) == 3
    outline = {
        "title": "Presenta 演示",
        "subtitle": "从文档到演示",
        "items": items,
    }

    confirmed = await client.post(
        f"/api/documents/{document_id}/outline/confirm", json=outline
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["hasOutline"] is True

    deck_response = await client.post("/api/decks", json={"documentId": document_id})
    assert deck_response.status_code == 201, deck_response.text
    deck_id = deck_response.json()["deck"]["id"]
    assert deck_response.json()["versionSeq"] == 1

    generate = await client.post(f"/api/decks/{deck_id}/generate")
    assert generate.status_code == 202, generate.text
    generation_job = await wait_job(client, generate.json()["jobId"])
    assert generation_job["status"] in {"succeeded", "partial"}, generation_job
    assert generation_job["result"]["slides"] == 3

    loaded = await client.get(f"/api/decks/{deck_id}")
    deck = loaded.json()["deck"]
    assert loaded.json()["versionSeq"] >= 2
    assert len(deck["slides"]) == 3
    assert deck["slides"][0]["layout"] == "cover"
    assert deck["slides"][-1]["layout"] == "ending"
    assert deck["meta"]["title"] == "Presenta 演示"

    patched = await client.patch(
        f"/api/decks/{deck_id}",
        json={
            "operations": [
                {"op": "replace", "path": "/slides/0/slots/title", "value": "新的封面标题"},
                {"op": "replace", "path": "/motionLevel", "value": 0.35},
            ],
            "kind": "autosave",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["deck"]["slides"][0]["slots"]["title"] == "新的封面标题"
    assert patched.json()["deck"]["motionLevel"] == 0.35
    patch_seq = patched.json()["versionSeq"]

    versions = (await client.get(f"/api/decks/{deck_id}/versions")).json()
    kinds = {version["kind"] for version in versions}
    assert {"anchor", "milestone", "autosave"} <= kinds

    generation_seq = next(version["seq"] for version in versions if version["kind"] == "milestone")
    rolled = await client.post(
        f"/api/decks/{deck_id}/rollback", json={"targetSeq": generation_seq}
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["versionSeq"] == generation_seq
    assert rolled.json()["deck"]["slides"][0]["slots"]["title"] != "新的封面标题"

    redone = await client.post(
        f"/api/decks/{deck_id}/rollback", json={"targetSeq": patch_seq}
    )
    assert redone.status_code == 200, redone.text
    assert redone.json()["versionSeq"] == patch_seq
    assert redone.json()["deck"]["slides"][0]["slots"]["title"] == "新的封面标题"

    bad_patch = await client.patch(
        f"/api/decks/{deck_id}",
        json={"operations": [{"op": "replace", "path": "/slides/0/layout", "value": "cover"}]},
    )
    assert bad_patch.status_code == 422
    assert bad_patch.json()["code"] == "validation_failed"

    themes = await client.get("/api/themes")
    assert themes.status_code == 200
    assert len(themes.json()) == 6

    anonymous = AsyncClient(transport=client._transport, base_url="http://test")
    async with anonymous:
        denied = await anonymous.get(f"/api/decks/{deck_id}")
        assert denied.status_code == 401


async def test_unauthenticated_upload_rejected(client: AsyncClient) -> None:
    anonymous = AsyncClient(transport=client._transport, base_url="http://test")
    async with anonymous:
        response = await anonymous.get("/api/documents")
    assert response.status_code == 401