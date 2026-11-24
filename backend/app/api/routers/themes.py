import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.core.errors import NotFoundError, PayloadTooLargeError, ValidationFailedError
from app.db.models import Theme
from app.services.storage import safe_key, storage
from app.services.theme.manifest import load_manifest, manifest_css_variables, wcag_report

router = APIRouter(prefix="/themes", tags=["themes"])
_MANIFEST_DIR = Path(__file__).resolve().parents[3] / "templates" / "themes"
_DANGEROUS_JS = re.compile(
    r"\b(eval|Function|fetch|XMLHttpRequest|WebSocket|importScripts)\b|child_process|require\s*\(",
    re.IGNORECASE,
)


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


@router.post("", status_code=201)
async def upload_theme_pack(
    user: CurrentUser,
    session: SessionDep,
    file: Annotated[UploadFile, File(...)],
    name: Annotated[str, Form()] = "自定义主题",
) -> dict[str, Any]:
    blob = await file.read(settings.max_upload_bytes + 1)
    if not blob:
        raise ValidationFailedError("模板包为空")
    if len(blob) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"模板包超过 {settings.max_upload_mb}MB 上限")
    try:
        archive = zipfile.ZipFile(BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ValidationFailedError("模板包不是有效 ZIP") from exc
    total = sum(info.file_size for info in archive.infolist())
    if total > settings.max_upload_bytes * 4:
        raise PayloadTooLargeError("模板包展开大小超过限制")
    for info in archive.infolist():
        path = Path(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValidationFailedError("模板包包含非法路径")
    try:
        raw_manifest = archive.read("manifest.json")
    except KeyError as exc:
        raise ValidationFailedError("模板包缺少 manifest.json") from exc
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise ValidationFailedError("manifest.json 不是有效 JSON") from exc
    for info in archive.infolist():
        if not info.filename.endswith((".js", ".html", ".svg", ".css")):
            continue
        content = archive.read(info.filename).decode("utf-8", errors="ignore")
        if _DANGEROUS_JS.search(content) or "<script" in content.lower():
            raise ValidationFailedError(
                f"{info.filename} 包含禁止的动态执行或网络 API"
            )
    theme_id = f"custom-{uuid4().hex[:20]}"
    manifest["id"] = theme_id
    manifest["name"] = name[:120] or str(manifest.get("name") or "自定义主题")
    manifest["version"] = 1
    from app.services.theme.manifest import validate_manifest

    issues = validate_manifest(manifest)
    layouts = set(manifest.get("layouts") or [])
    missing_layouts = set(("cover", "toc", "bullets", "split-lr", "split-tb", "cards-3",
                           "chart", "big-number", "quote", "compare", "timeline", "process",
                           "full-image", "ending")) - layouts
    declared_missing = set(manifest.get("missingLayouts") or [])
    if missing_layouts - declared_missing:
        issues.append(f"缺少版式：{sorted(missing_layouts - declared_missing)}")
    report = wcag_report(manifest)
    if not report.get("passesAA"):
        issues.append("主题存在低于 WCAG AA 的正文对比度组合")
    if issues:
        raise ValidationFailedError("模板包校验失败", details={"issues": issues})
    package_key = safe_key(f"themes/{user.id}", "zip")
    await storage.put_bytes(package_key, blob, "application/zip")
    manifest_path = _MANIFEST_DIR / f"{theme_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    session.add(
        Theme(
            id=theme_id,
            owner_id=user.id,
            name=manifest["name"],
            manifest=manifest,
            package_key=package_key,
            status="approved",
        )
    )
    await session.flush()
    return _public(manifest)


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
