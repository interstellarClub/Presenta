"""真实 DeepSeek 冒烟：必须配置真实 DEEPSEEK_API_KEY，不接受 mock 结论。

用法：
    cd backend
    DEEPSEEK_API_KEY=sk-... .venv/bin/python scripts/smoke_deepseek.py

退出码 0 表示真实 API 完成大纲 + 逐页生成，且 usage_ledger.provider=deepseek。
"""

import asyncio
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="presenta-deepseek-smoke-"))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{TMP / 'deepseek.db'}")
os.environ.setdefault("LOCAL_STORAGE_DIR", str(TMP / "storage"))
os.environ.setdefault("QUEUE_BACKEND", "local")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ["LLM_PROVIDER"] = "deepseek"

MARKDOWN = """# 研究背景

团队每周需要把长篇报告整理成演示文稿，人工重排结构平均耗时半天。

# 核心方法

结构化 Schema 是唯一真相，编辑只对 Schema 打补丁，不反解析 DOM。

# 实验结果

在 12 份报告中，平均成稿时间从 4.5 小时下降到 38 分钟，人工返工率下降 42%。

# 结论

图表数值必须逐字符串匹配原文，任何无法保真的部分都要显式标注降级。
"""


async def main() -> int:
    from app.core.config import settings

    if not settings.deepseek_api_key_configured:
        print(
            "FAIL: DEEPSEEK_API_KEY 未配置或为占位值；本脚本只接受真实 Key，不会回退 mock。",
            file=sys.stderr,
        )
        return 2

    from sqlalchemy import func, select

    from app.db.models import Document, UsageLedger, User
    from app.db.session import SessionFactory, dispose_engine, ensure_schema
    from app.services.ingest.markdown import build_ast
    from app.services.outline.generator import generate_outline
    from app.services.pages.generator import generate_pages
    from app.services.theme.seed import seed_builtin_themes

    await ensure_schema()
    started = time.monotonic()
    async with SessionFactory() as session:
        await seed_builtin_themes(session)
        user = User(
            email=f"deepseek-smoke-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="smoke-not-a-login",
            display_name="DeepSeek Smoke",
        )
        session.add(user)
        await session.flush()
        document = Document(
            user_id=user.id,
            title="真实 API 验收文档",
            source_type="editor_md",
            normalized_md=MARKDOWN,
            ast=build_ast(MARKDOWN),
            status="ready",
        )
        session.add(document)
        await session.flush()
        outline = await generate_outline(session, document, user_id=user.id)
        print(f"outline ok: {len(outline.items)} items")

        from app.api.schemas.deck import Deck, DeckMeta
        from app.db.models import Deck as DeckRow

        deck_row = DeckRow(
            user_id=user.id,
            document_id=document.id,
            title=outline.title,
            theme_id="academic",
        )
        session.add(deck_row)
        await session.flush()
        from app.services.deck.versioning import create_version

        empty = Deck(id=deck_row.id.hex, meta=DeckMeta(title=outline.title))
        await create_version(
            session,
            deck_row,
            snapshot=empty.model_dump(mode="json", by_alias=True),
            patch=None,
            kind="anchor",
            created_by=user.id,
        )
        deck, versions = await generate_pages(
            session,
            deck_row=deck_row,
            document=document,
            outline=outline,
            user_id=user.id,
        )
        degraded_count = sum(s.degraded for s in deck.slides)
        layouts = [slide.layout for slide in deck.slides]
        print(
            f"pages ok: {len(deck.slides)} slides, degraded={degraded_count}, "
            f"layouts={sorted(set(layouts))}"
        )
        if degraded_count:
            print(
                "FAIL: 真实 API smoke 出现非预期 degraded 页，请检查提示词、修复轮次和 Schema",
                file=sys.stderr,
            )
            return 6
        if "chart" not in layouts:
            print(
                "FAIL: 真实 API smoke 未覆盖图表页，不能证明数值和 derived provenance 链路",
                file=sys.stderr,
            )
            return 7

        usage_rows = (
            await session.scalars(
                select(UsageLedger).where(UsageLedger.provider == "deepseek")
            )
        ).all()
        total = await session.scalar(
            select(func.count(UsageLedger.id)).where(UsageLedger.provider == "deepseek")
        )
        if not usage_rows or int(total or 0) != len(usage_rows):
            print("FAIL: usage_ledger 没有记录真实 deepseek 调用", file=sys.stderr)
            return 3
        models = {row.model for row in usage_rows}
        print(
            f"usage ok: {len(usage_rows)} rows, models={sorted(models)}, "
            f"thinking={sorted({row.thinking for row in usage_rows})}"
        )
        await session.commit()


    if settings.llm_provider != "deepseek":
        print("FAIL: LLM_PROVIDER 不是 deepseek", file=sys.stderr)
        return 4
    if any(model != settings.deepseek_model for model in models):
        print("FAIL: usage 中出现 mock 模型", file=sys.stderr)
        return 5
    await dispose_engine()
    print(f"PASS: real DeepSeek smoke in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
