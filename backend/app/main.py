import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from app.api.routers import auth, decks, documents, exports, jobs, shares, themes
from app.core.config import settings
from app.core.errors import AppError
from app.db.session import SessionFactory, dispose_engine, engine, ensure_schema
from app.services.theme.seed import seed_builtin_themes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("presenta")

ALLOWED_ORIGINS = {
    settings.web_origin,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.uses_sqlite or settings.app_env != "prod":
        await ensure_schema()
    async with SessionFactory() as session:
        try:
            await seed_builtin_themes(session)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("theme seeding skipped: %s", exc)
    logger.info(
        "presenta api ready env=%s db=%s queue=%s storage=%s llm=%s",
        settings.app_env,
        "sqlite" if settings.uses_sqlite else "postgres",
        settings.queue_backend,
        settings.storage_backend,
        settings.llm_provider,
    )
    if settings.llm_provider == "mock":
        logger.warning("LLM provider is 'mock' - generation output is deterministic dev data")
    if settings.secret_key.startswith("dev-insecure"):
        logger.warning("SECRET_KEY is the development default; set a strong value before deploy")
    yield
    await dispose_engine()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def guard_origin(request: Request, call_next: Any) -> Any:
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"code": "forbidden", "message": "cross-origin request rejected"},
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(PydanticValidationError)
async def handle_validation(_request: Request, exc: PydanticValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_failed",
            "message": "请求参数未通过校验",
            "details": {"errors": exc.errors(include_url=False, include_context=False)},
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "服务器内部错误"},
    )


for router in (
    auth.router,
    documents.router,
    decks.router,
    jobs.router,
    themes.router,
    exports.router,
    shares.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
async def health() -> dict[str, Any]:
    db_ok = True
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "queue": settings.queue_backend,
        "storage": settings.storage_backend,
        "llm": settings.llm_provider,
        "env": settings.app_env,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}