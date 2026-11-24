import json

import pytest
from httpx import AsyncClient

from app.services.export.render_svc import RenderResult
from tests.conftest import wait_job

MARKDOWN = """# 背景

团队需要把报告转成演示文稿。

# 方案

结构化 Schema 是唯一真相，编辑改 Schema 不改 HTML。

# 结论

图表数值必须逐字符串匹配原文。
"""


async def _prepare_deck(client: AsyncClient) -> str:
    created = await client.post(
        "/api/documents/editor",
        json={"title": "导出测试文稿", "markdown": MARKDOWN},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]
    await wait_job(client, created.json()["jobId"])

    events: list[dict] = []
    async with client.stream("POST", f"/api/documents/{document_id}/outline") as response:
        current = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append({"event": current, "data": json.loads(line.split(":", 1)[1])})
    items = [event["data"] for event in events if event["event"] == "item"]
    outline = {"title": "导出演示", "subtitle": "M3 验证", "items": items}
    confirmed = await client.post(
        f"/api/documents/{document_id}/outline/confirm", json=outline
    )
    assert confirmed.status_code == 200, confirmed.text

    deck = await client.post("/api/decks", json={"documentId": document_id, "outline": outline})
    assert deck.status_code == 201, deck.text
    deck_id = deck.json()["deck"]["id"]
    generate = await client.post(f"/api/decks/{deck_id}/generate")
    assert generate.status_code == 202, generate.text
    job = await wait_job(client, generate.json()["jobId"])
    assert job["status"] in {"succeeded", "partial"}, job
    return deck_id


@pytest.fixture
def fake_render(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_pdf(*, slides_html, theme_css, page_size="", margin=""):
        assert slides_html, "render-svc should receive slide markup"
        return RenderResult(
            content=b"%PDF-1.4\n%%EOF\n",
            content_type="application/pdf",
            degraded=False,
            notes=["fake render"],
        )

    async def fake_gif(
        *,
        slides_html,
        theme_css,
        fps=15,
        seconds=8,
        max_width=1280,
        frame_times=None,
        dark_theme=False,
        slide_steps=None,
    ):
        assert slides_html
        return RenderResult(
            content=b"GIF89a-fake",
            content_type="image/gif",
            degraded=True,
            notes=["GIF 256 色"],
        )

    monkeypatch.setattr("app.services.export.service.render_pdf", fake_pdf)
    monkeypatch.setattr("app.services.export.service.render_png_sequence", fake_gif)


async def test_html_export_and_download(client: AsyncClient, invited_user: dict) -> None:
    deck_id = await _prepare_deck(client)
    started = await client.post(
        "/api/exports", json={"deckId": deck_id, "format": "html"}
    )
    assert started.status_code == 202, started.text
    artifact = started.json()["artifact"]
    assert artifact is not None
    download = await client.get(artifact["downloadUrl"])
    assert download.status_code == 200
    body = download.text
    assert body.startswith("<!doctype html>")
    assert "presenta-slide" in body
    assert "结构化 Schema" in body or "Schema" in body


async def test_pdf_gif_pptx_exports(
    client: AsyncClient, invited_user: dict, fake_render: None
) -> None:
    deck_id = await _prepare_deck(client)

    for fmt, magic in (("pdf", b"%PDF-1.4"), ("gif", b"GIF89a"), ("pptx", b"PK\x03\x04")):
        started = await client.post("/api/exports", json={"deckId": deck_id, "format": fmt})
        assert started.status_code == 202, started.text
        job = await wait_job(client, started.json()["jobId"])
        assert job["status"] in {"succeeded", "partial"}, (fmt, job)
        artifact_id = job["result"]["artifactId"]
        download = await client.get(f"/api/exports/{artifact_id}/download")
        assert download.status_code == 200, download.text
        assert download.content.startswith(magic), fmt

    mp4 = await client.post("/api/exports", json={"deckId": deck_id, "format": "mp4"})
    assert mp4.status_code == 409
    assert "WebCodecs" in mp4.json()["message"]


async def test_share_flow_and_access_logs(client: AsyncClient, invited_user: dict) -> None:
    deck_id = await _prepare_deck(client)
    created = await client.post(
        "/api/shares",
        json={
            "deckId": deck_id,
            "password": "share-secret-123",
            "ttlHours": 2,
            "allowDownload": True,
            "formats": ["html", "pdf"],
        },
    )
    assert created.status_code == 201, created.text
    share = created.json()
    slug = share["slug"]

    info = await client.get(f"/api/shares/guest/{slug}")
    assert info.status_code == 200
    assert info.json()["requiresPassword"] is True
    assert info.json()["title"] == "导出演示"

    wrong = await client.post(f"/api/shares/guest/{slug}/unlock", json={"password": "nope"})
    assert wrong.status_code == 401

    unlocked = await client.post(
        f"/api/shares/guest/{slug}/unlock", json={"password": "share-secret-123"}
    )
    assert unlocked.status_code == 200, unlocked.text
    payload = unlocked.json()
    assert len(payload["deck"]["slides"]) == 3
    assert payload["allowDownload"] is True
    assert "pdf" in payload["downloadFormats"]

    download = await client.post(f"/api/shares/guest/{slug}/downloads/html")
    assert download.status_code == 200, download.text
    file_url = download.json()["url"]
    content = await client.get(file_url)
    assert content.status_code == 200
    assert "presenta-slide" in content.text

    blocked = await client.post(f"/api/shares/guest/{slug}/downloads/mp4")
    assert blocked.status_code == 409

    revoked = await client.post(f"/api/shares/{share['id']}/revoke")
    assert revoked.status_code == 200
    gone = await client.get(f"/api/shares/guest/{slug}")
    assert gone.status_code == 404


async def test_cleanup_keeps_unexpired_artifacts(client: AsyncClient, invited_user: dict) -> None:
    from app.db.session import SessionFactory
    from app.services.cleanup import run_cleanup

    deck_id = await _prepare_deck(client)
    started = await client.post("/api/exports", json={"deckId": deck_id, "format": "html"})
    assert started.status_code == 202
    artifact_id = started.json()["artifact"]["id"]

    async with SessionFactory() as session:
        counts = await run_cleanup(session)
        await session.commit()

    assert counts["artifacts"] == 0
    still_there = await client.get(f"/api/exports/{artifact_id}")
    assert still_there.status_code == 200
