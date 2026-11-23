from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import SessionDep
from app.core.errors import NotFoundError
from app.db.models import Theme
from app.services.theme.manifest import load_manifest, manifest_css_variables, wcag_report

router = APIRouter(prefix="/themes", tags=["themes"])


def _public(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": manifest["id"],
        "name": manifest.get("name"),
        "version": manifest.get("version", 1),
        "tokens": manifest.get("tokens"),
        "cssVariables": manifest_css_variables(manifest),
        "layouts": manifest.get("layouts"),
        "motionCapabilities": manifest.get("motionCapabilities"),
        "fonts": manifest.get("fonts"),
        "typography": manifest.get("typography"),
        "wcag": wcag_report(manifest),
    }


@router.get("", response_model=list[dict[str, Any]])
async def list_themes(session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Theme).where(Theme.status.in_(["builtin", "approved"])).order_by(Theme.id)
        )
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            manifest = load_manifest(row.id if row.status == "builtin" else row.id)
        except Exception:
            manifest = row.manifest
        result.append(_public({**manifest, "id": row.id, "name": row.name}))
    return result


@router.get("/{theme_id}", response_model=dict[str, Any])
async def get_theme(theme_id: str) -> dict[str, Any]:
    try:
        manifest = load_manifest(theme_id)
    except Exception as exc:
        raise NotFoundError("主题不存在") from exc
    return _public(manifest)


@router.get("/{theme_id}/wcag", response_model=dict[str, Any])
async def theme_wcag(theme_id: str) -> dict[str, Any]:
    try:
        manifest = load_manifest(theme_id)
    except Exception as exc:
        raise NotFoundError("主题不存在") from exc
    return wcag_report(manifest)