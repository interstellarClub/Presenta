"""迁移测试：历史重复 doc_assets 去重 + upgrade/downgrade 循环。"""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import MetaData, Table, create_engine, text


def _run_alembic(db_url: str, target: str) -> None:
    backend_dir = Path(__file__).parent.parent
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["APP_ENV"] = "test"
    env["LLM_PROVIDER"] = "mock"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade {target} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")


def test_migration_dedup_duplicate_assets() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="presenta-mig-test-"))
    db_path = tmp / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "b717060f2795")

    engine = create_engine(sync_url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    users_tbl = Table("users", metadata)
    docs_tbl = Table("documents", metadata)
    assets_tbl = Table("doc_assets", metadata)

    user_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    sha = "a" * 64
    keep_asset_id = "00000000-0000-0000-0000-00000000000a"
    duplicate_asset_id = "11111111-1111-1111-1111-111111111111"
    with engine.connect() as conn:
        conn.execute(
            users_tbl.insert().values(
                id=user_id, email="mig@example.com", password_hash="x", status="active"
            )
        )
        conn.execute(
            docs_tbl.insert().values(
                id=doc_id,
                user_id=user_id,
                title="test",
                source_type="editor_md",
                status="ready",
                degraded=False,
                normalized_md=f"![](asset://{duplicate_asset_id})",
            )
        )
        conn.execute(
            assets_tbl.insert().values(
                id=keep_asset_id,
                document_id=doc_id,
                kind="image",
                sha256=sha,
                storage_key="key1",
                ref_count=0,
            )
        )
        conn.execute(
            assets_tbl.insert().values(
                id=duplicate_asset_id,
                document_id=doc_id,
                kind="image",
                sha256=sha,
                storage_key="key2",
                meta={"aliases": {"a1": "alias_key1"}},
                ref_count=0,
            )
        )
        conn.commit()

    _run_alembic(db_url, "c4d5e6f70819")

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM doc_assets WHERE document_id = :doc AND sha256 = :sha"
            ),
            {"doc": str(doc_id), "sha": sha},
        ).scalar()
        assert count == 1

        kept_meta = conn.execute(
            text(
                "SELECT meta FROM doc_assets WHERE document_id = :doc AND sha256 = :sha"
            ),
            {"doc": str(doc_id), "sha": sha},
        ).scalar()
        assert kept_meta is not None
        normalized_md = conn.execute(
            text("SELECT normalized_md FROM documents WHERE id = :doc"),
            {"doc": str(doc_id)},
        ).scalar()
        assert f"asset://{keep_asset_id}" in normalized_md
        assert f"asset://{duplicate_asset_id}" not in normalized_md

    engine.dispose()


def test_migration_upgrade_downgrade_cycle() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="presenta-mig-cycle-"))
    db_path = tmp / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    _run_alembic(db_url, "c4d5e6f70819")
    _run_alembic(db_url, "b717060f2795")
    _run_alembic(db_url, "c4d5e6f70819")
