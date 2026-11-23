import asyncio
import os
import tempfile
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="presenta-smoke-"))
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP / 'smoke.db'}"
os.environ["LOCAL_STORAGE_DIR"] = str(TMP / "storage")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["QUEUE_BACKEND"] = "local"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["RATE_LIMIT_REGISTER_PER_HOUR"] = "1000"

import httpx
from httpx import ASGITransport, AsyncClient

MARKDOWN = """# 背景

团队需要把报告转成演示文稿，过去要花半天重排结构。

# 方案

结构化 Schema 是唯一真相，编辑改 Schema 而不是 HTML。

# 结论

图表数值必须逐字符串匹配原文。
"""

TERMINAL = {"succeeded", "failed", "cancelled", "partial"}


async def wait_job(client: AsyncClient, job_id: str, timeout: float = 30.0) -> dict:
    for _ in range(int(timeout / 0.05)):
        response = await client.get(f"/api/jobs/{job_id}")
        payload = response.json()
        if payload["status"] in TERMINAL:
            return payload
        await asyncio.sleep(0.05)
    raise RuntimeError(f"job {job_id} stalled")


async def main() -> int:
    from app.cli.invite import create_invite
    from app.db.session import SessionFactory, ensure_schema
    from app.main import app
    from app.services.export.render_svc import RenderResult
    from app.services.theme.seed import seed_builtin_themes

    await ensure_schema()
    async with SessionFactory() as session:
        await seed_builtin_themes(session)
        _, invite = await create_invite(session, label="smoke", uses=3)
        await session.commit()

    async def fake_pdf(**_: object) -> RenderResult:
        return RenderResult(b"%PDF-1.4\n%%EOF", "application/pdf", False, ["fake pdf"])

    async def fake_gif(**_: object) -> RenderResult:
        return RenderResult(b"GIF89a-fake", "image/gif", True, ["GIF 256 色"])

    import app.services.export.service as export_service

    export_service.render_pdf = fake_pdf  # type: ignore[assignment]
    export_service.render_png_sequence = fake_gif  # type: ignore[assignment]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://smoke") as client:
        email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
        registered = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "presenta12345",
                "inviteCode": invite,
                "displayName": "Smoke",
            },
        )
        assert registered.status_code == 201, registered.text
        print("auth ok")

        created = await client.post(
            "/api/documents/editor", json={"title": "冒烟文档", "markdown": MARKDOWN}
        )
        assert created.status_code == 201, created.text
        document_id = created.json()["document"]["id"]
        ingest = await wait_job(client, created.json()["jobId"])
        assert ingest["status"] == "succeeded", ingest
        print("ingest ok", ingest["result"])

        detail = (await client.get(f"/api/documents/{document_id}")).json()
        items = [
            {
                "id": f"item-{index + 1}",
                "title": section["title"],
                "points": [section["preview"][:36] or section["title"]],
                "sectionId": section["id"],
            }
            for index, section in enumerate(detail["sections"])
        ]
        outline = {"title": "冒烟演示", "subtitle": "", "items": items}
        confirmed = await client.post(
            f"/api/documents/{document_id}/outline/confirm", json=outline
        )
        assert confirmed.status_code == 200, confirmed.text
        print("outline confirm ok")

        deck = await client.post("/api/decks", json={"documentId": document_id, "outline": outline})
        assert deck.status_code == 201, deck.text
        deck_id = deck.json()["deck"]["id"]
        generated = await client.post(f"/api/decks/{deck_id}/generate")
        assert generated.status_code == 202, generated.text
        generation = await wait_job(client, generated.json()["jobId"])
        assert generation["status"] in {"succeeded", "partial"}, generation
        print("generate ok", generation["result"])

        loaded = (await client.get(f"/api/decks/{deck_id}")).json()
        print("slides", len(loaded["deck"]["slides"]), "version", loaded["versionSeq"])

        for fmt, magic in (("html", b"<!doctype html>"), ("pdf", b"%PDF"), ("gif", b"GIF89a"), ("pptx", b"PK")):
            started = await client.post("/api/exports", json={"deckId": deck_id, "format": fmt})
            assert started.status_code == 202, (fmt, started.text)
            body = started.json()
            if body.get("artifact"):
                artifact = body["artifact"]
            else:
                job = await wait_job(client, body["jobId"])
                assert job["status"] in {"succeeded", "partial"}, (fmt, job)
                artifact = {
                    "downloadUrl": f"/api/exports/{job['result']['artifactId']}/download"
                }
            download = await client.get(artifact["downloadUrl"])
            assert download.status_code == 200, (fmt, download.text)
            assert download.content.startswith(magic), (fmt, download.content[:24])
            print(f"export {fmt} ok", len(download.content), "bytes")

        shared = await client.post(
            "/api/shares",
            json={
                "deckId": deck_id,
                "password": "share-pass-1",
                "ttlHours": 2,
                "allowDownload": True,
                "formats": ["html"],
            },
        )
        assert shared.status_code == 201, shared.text
        slug = shared.json()["slug"]
        unlocked = await client.post(
            f"/api/shares/guest/{slug}/unlock", json={"password": "share-pass-1"}
        )
        assert unlocked.status_code == 200, unlocked.text
        guest_download = await client.post(f"/api/shares/guest/{slug}/downloads/html")
        assert guest_download.status_code == 200, guest_download.text
        guest_file = await client.get(guest_download.json()["url"])
        assert guest_file.content.startswith(b"<!doctype html>")
        print("share ok", slug)

    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))