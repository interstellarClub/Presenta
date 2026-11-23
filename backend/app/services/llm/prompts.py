from pathlib import Path

from app.core.errors import NotFoundError

_CACHE: dict[str, str] = {}


def load_prompt(service: str, name: str) -> str:
    key = f"{service}/{name}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parents[1] / service / "prompts" / f"{name}.md"
    if not path.exists():
        raise NotFoundError(f"prompt '{key}' not found")
    text = path.read_text(encoding="utf-8")
    _CACHE[key] = text
    return text


def render(template: str, **values: str) -> str:
    result = template
    for name, value in values.items():
        result = result.replace("{" + name + "}", value)
    return result