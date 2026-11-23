from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Presenta"
    api_prefix: str = "/api"
    web_origin: str = "http://localhost:5173"

    secret_key: str = "dev-insecure-secret-change-me"
    session_ttl_hours: int = 168
    invite_hmac_salt: str = "dev-invite-salt"

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["local", "arq"] = "local"

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: Path = BACKEND_DIR / ".storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "presenta"
    s3_key: str = "minioadmin"
    s3_secret: str = "minioadmin"
    s3_region: str = "us-east-1"

    llm_provider: Literal["mock", "deepseek"] = "mock"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_thinking: bool = True
    llm_timeout_s: int = 120
    llm_max_retries: int = 2
    llm_max_tokens: int = 8192
    batch_concurrency_per_user: int = 3

    pandoc_path: str = "pandoc"
    render_svc_url: str = "http://localhost:8100"
    render_svc_token: str = "dev-render-token"

    session_cookie: str = "presenta_session"
    session_cookie_secure: bool = False
    share_default_ttl_hours: int = 72
    purge_retention_days: int = 7
    download_url_ttl_s: int = 300

    max_upload_mb: int = 50
    max_deck_pages: int = 500
    ingest_timeout_s: int = 120
    max_patch_ops: int = 200

    rate_limit_register_per_hour: int = 5
    rate_limit_login_per_hour: int = 30
    rate_limit_window_s: int = 3600

    fonts_manifest_version: str = "1"
    layout_count: int = 14

    @field_validator("local_storage_dir", mode="before")
    @classmethod
    def _resolve_storage_dir(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @property
    def is_dev(self) -> bool:
        return self.app_env != "prod"

    @property
    def uses_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()