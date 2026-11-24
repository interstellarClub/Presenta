"""配置安全测试：占位 Key 拒绝、SecretStr 不泄露、lifespan 启动校验、WorkerSettings 导入。"""

import pytest
from pydantic import SecretStr

from app.core.config import Settings


def test_placeholder_zh_key_rejected() -> None:
    s = Settings(deepseek_api_key=SecretStr("请填入真实 Key（不要提交到仓库）"))
    assert not s.deepseek_api_key_configured


def test_placeholder_sk_dots_rejected() -> None:
    s = Settings(deepseek_api_key=SecretStr("sk-..."))
    assert not s.deepseek_api_key_configured


def test_placeholder_replace_me_rejected() -> None:
    s = Settings(deepseek_api_key=SecretStr("replace-me"))
    assert not s.deepseek_api_key_configured


def test_short_key_rejected() -> None:
    s = Settings(deepseek_api_key=SecretStr("sk-short"))
    assert not s.deepseek_api_key_configured


def test_real_key_accepted() -> None:
    s = Settings(deepseek_api_key=SecretStr("deepseek-test-key-1234567890abcdef"))
    assert s.deepseek_api_key_configured


def test_none_key_rejected() -> None:
    s = Settings(deepseek_api_key=None)
    assert not s.deepseek_api_key_configured


def test_secret_str_not_leaked_in_repr() -> None:
    raw = "deepseek-test-key-1234567890abcdef"
    s = Settings(deepseek_api_key=SecretStr(raw))
    assert raw not in repr(s)
    assert raw not in repr(s.deepseek_api_key)


def test_secret_str_not_leaked_in_str() -> None:
    raw = "deepseek-test-key-1234567890abcdef"
    s = Settings(deepseek_api_key=SecretStr(raw))
    assert raw not in str(s)


async def test_lifespan_fails_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.main import lifespan

    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        async with lifespan(None):
            pass


async def test_lifespan_fails_with_placeholder_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.main import lifespan

    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr("请填入真实 Key（不要提交到仓库）"))
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        async with lifespan(None):
            pass


def test_worker_settings_imports() -> None:
    from app.workers.arq_settings import WorkerSettings

    names = [f.name for f in WorkerSettings.functions]
    assert "run_generate_job" in names
    assert "run_ingest_job" in names
    assert "run_export_job" in names
    assert "run_cleanup_job" in names
    assert "run_job" in names
    assert len(WorkerSettings.cron_jobs) >= 1
