import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import ValidationFailedError
from app.services.deck.layouts import LAYOUTS

_MANIFEST_DIR = Path(__file__).resolve().parents[2] / "templates" / "themes"

_REQUIRED_TOKEN_GROUPS = {"color", "font", "space", "radius", "shadow"}
_ALLOWED_CSS_PROPERTIES = {
    "--color-bg",
    "--color-surface",
    "--color-text",
    "--color-muted",
    "--color-primary",
    "--color-accent",
    "--color-border",
    "--color-on-primary",
    "--font-display",
    "--font-body",
    "--font-mono",
    "--size-1",
    "--size-2",
    "--size-3",
    "--size-4",
    "--size-5",
    "--radius-sm",
    "--radius-md",
    "--radius-lg",
    "--shadow-sm",
    "--shadow-md",
}


def list_builtin_theme_ids() -> list[str]:
    return sorted(path.stem for path in _MANIFEST_DIR.glob("*.json"))


def load_manifest(theme_id: str) -> dict[str, Any]:
    path = _MANIFEST_DIR / f"{theme_id}.json"
    if not path.exists():
        raise ValidationFailedError(f"unknown theme '{theme_id}'", details={"themes": list_builtin_theme_ids()})
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for key in ("id", "name", "tokens", "layouts"):
        if key not in manifest:
            issues.append(f"manifest missing '{key}'")
    tokens = manifest.get("tokens") or {}
    if isinstance(tokens, dict):
        missing = _REQUIRED_TOKEN_GROUPS - set(tokens)
        if missing:
            issues.append(f"tokens missing groups {sorted(missing)}")
    layouts = manifest.get("layouts") or []
    unknown = [layout for layout in layouts if layout not in LAYOUTS]
    if unknown:
        issues.append(f"unknown layouts in manifest: {unknown}")
    fonts = manifest.get("fonts") or {}
    if fonts.get("version") != settings.fonts_manifest_version:
        issues.append("font manifest version mismatch with server renderer")
    return issues


def manifest_css_variables(manifest: dict[str, Any]) -> dict[str, str]:
    tokens = manifest.get("tokens") or {}
    variables: dict[str, str] = {}
    for name, value in (tokens.get("cssVariables") or {}).items():
        if name in _ALLOWED_CSS_PROPERTIES:
            variables[name] = str(value)
    return variables


def load_all_builtin() -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for theme_id in list_builtin_theme_ids():
        manifest = load_manifest(theme_id)
        issues = validate_manifest(manifest)
        if issues:
            raise ValidationFailedError(
                f"builtin theme '{theme_id}' is invalid", details={"issues": issues}
            )
        manifests.append(manifest)
    return manifests


def relative_luminance(hex_color: str) -> float:
    color = hex_color.lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    if len(color) != 6:
        raise ValueError("invalid hex color")
    channels = [int(color[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def wcag_report(manifest: dict[str, Any]) -> dict[str, Any]:
    color = (manifest.get("tokens") or {}).get("color") or {}
    background = color.get("bg", "#FFFFFF")
    checks: list[dict[str, Any]] = []
    for name in ("text", "muted", "primary", "accent"):
        foreground = color.get(name)
        if not foreground:
            continue
        ratio = contrast_ratio(foreground, background)
        checks.append(
            {
                "pair": f"{name}/bg",
                "ratio": round(ratio, 2),
                "passesAA": ratio >= 4.5,
                "passesLargeAA": ratio >= 3.0,
            }
        )
    return {"checks": checks, "passesAA": all(check["passesAA"] for check in checks)}