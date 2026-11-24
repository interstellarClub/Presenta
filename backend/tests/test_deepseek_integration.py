"""真实 DeepSeek 集成测试。

默认跳过；只有显式提供真实 Key 时才运行：
    DEEPSEEK_API_KEY=sk-... DEEPSEEK_REAL_NETWORK=1 pytest -m deepseek -q

普通单元测试仍使用 mock（见 tests/conftest.py），不会与本套件共用通过结论。
"""

import os

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.errors import UpstreamError
from app.services.llm.gateway import generate_structured

pytestmark = pytest.mark.deepseek

NETWORK = os.environ.get("DEEPSEEK_REAL_NETWORK") == "1"


@pytest.fixture
def real_provider(monkeypatch: pytest.MonkeyPatch):
    if not settings.deepseek_api_key_configured:
        pytest.skip("需要真实 DEEPSEEK_API_KEY（在 .env 或环境变量中配置）")
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    return settings


@pytest.mark.skipif(not NETWORK, reason="需要 DEEPSEEK_REAL_NETWORK=1")
async def test_invalid_key_returns_upstream_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.outline import Outline
    from app.db.session import SessionFactory

    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(
        settings,
        "deepseek_api_key",
        SecretStr("invalid-key-for-acceptance"),
    )
    async with SessionFactory() as session:
        with pytest.raises(UpstreamError) as excinfo:
            await generate_structured(
                session,
                purpose="outline",
                schema=Outline,
                system_prompt="只输出 JSON",
                user_prompt="输出一个空大纲",
                mock_context={},
                thinking=False,
                repair_budget=0,
            )
        assert excinfo.value.details.get("reason") == "upstream_auth"


@pytest.mark.skipif(not NETWORK, reason="需要 DEEPSEEK_REAL_NETWORK=1")
async def test_real_outline_and_page(real_provider, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import select

    from app.api.schemas.deck import Deck, DeckMeta
    from app.db.models import Deck as DeckRow
    from app.db.models import Document, UsageLedger, User
    from app.db.session import SessionFactory
    from app.services.deck.versioning import create_version
    from app.services.ingest.markdown import build_ast
    from app.services.outline.generator import generate_outline
    from app.services.pages.generator import generate_pages

    markdown = """# 背景\n真实模型验收需要覆盖大纲和页面。\n
# 方法\n编辑只改 Schema，导出必须与编辑态一致。\n
# 结论\n所有来源必须逐字可回溯。\n"""
    async with SessionFactory() as session:
        user = User(
            email=f"deepseek-{os.urandom(4).hex()}@example.com",
            password_hash="not-a-login",
        )
        session.add(user)
        await session.flush()
        document = Document(
            user_id=user.id,
            title="真实 API 集成",
            source_type="editor_md",
            normalized_md=markdown,
            ast=build_ast(markdown),
            status="ready",
        )
        session.add(document)
        await session.flush()
        outline = await generate_outline(session, document, user_id=user.id)
        assert outline.items

        deck_row = DeckRow(
            user_id=user.id, document_id=document.id, title=outline.title, theme_id="academic"
        )
        session.add(deck_row)
        await session.flush()
        await create_version(
            session,
            deck_row,
            snapshot=Deck(id=deck_row.id.hex, meta=DeckMeta(title=outline.title)).model_dump(
                mode="json", by_alias=True
            ),
            patch=None,
            kind="anchor",
            created_by=user.id,
        )
        deck, _ = await generate_pages(
            session, deck_row=deck_row, document=document, outline=outline, user_id=user.id
        )
        assert deck.slides
        rows = (
            await session.scalars(select(UsageLedger).where(UsageLedger.provider == "deepseek"))
        ).all()
        assert rows
        assert {row.model for row in rows} == {settings.deepseek_model}
        await session.rollback()
