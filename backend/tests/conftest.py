import asyncio
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="presenta-test-"))
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["LOCAL_STORAGE_DIR"] = str(_TMP / "storage")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["QUEUE_BACKEND"] = "local"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["RATE_LIMIT_REGISTER_PER_HOUR"] = "10000"
os.environ["RATE_LIMIT_LOGIN_PER_HOUR"] = "10000"

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import SessionFactory, dispose_engine, ensure_schema
from app.services.theme.seed import seed_builtin_themes

TERMINAL = {"succeeded", "failed", "cancelled", "partial"}


@pytest.fixture(scope="session")
async def client() -> AsyncClient:
    from app.main import app

    await ensure_schema()
    async with SessionFactory() as session:
        await seed_builtin_themes(session)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    await dispose_engine()


async def wait_job(client: AsyncClient, job_id: str, timeout_s: float = 20.0) -> dict:
    loops = int(timeout_s / 0.05)
    for _ in range(loops):
        response = await client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in TERMINAL:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout_s}s")


@pytest.fixture
async def invited_user(client: AsyncClient) -> dict:
    from app.cli.invite import create_invite

    async with SessionFactory() as session:
        _, raw_code = await create_invite(session, label="pytest", uses=5)
        await session.commit()

    import uuid

    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "presenta12345",
            "inviteCode": raw_code,
            "displayName": "测试用户",
        },
    )
    assert response.status_code == 201, response.text
    return {"email": email, "password": "presenta12345", "profile": response.json()["user"]}
