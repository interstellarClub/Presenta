from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    if settings.uses_sqlite:
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return kwargs


engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs())

SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if settings.uses_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ensure_schema() -> None:
    if settings.uses_sqlite:
        async with engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    await engine.dispose()