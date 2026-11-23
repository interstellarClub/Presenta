import asyncio
import base64
import binascii
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ExportDegradedError, UpstreamError


@dataclass
class RenderResult:
    content: bytes
    content_type: str
    degraded: bool
    notes: list[str]


async def _post(path: str, payload: dict[str, Any], timeout_s: float) -> httpx.Response:
    url = f"{settings.render_svc_url.rstrip('/')}{path}"
    headers = {"X-Render-Token": settings.render_svc_token}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            return await client.post(url, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise UpstreamError(f"render-svc unreachable: {exc}") from exc


async def render_pdf(
    *,
    slides_html: list[str],
    theme_css: str,
    page_size: str = "1280px 720px",
    margin: str = "0",
) -> RenderResult:
    response = await _post(
        "/render/pdf",
        {"slides": slides_html, "themeCss": theme_css, "pageSize": page_size, "margin": margin},
        timeout_s=300,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise UpstreamError(f"render-svc pdf failed ({response.status_code}): {detail}")
    data = response.json()
    return RenderResult(
        content=base64.b64decode(data["pdf"]),
        content_type="application/pdf",
        degraded=bool(data.get("degraded")),
        notes=list(data.get("notes") or []),
    )


async def render_png_sequence(
    *,
    slides_html: list[str],
    theme_css: str,
    fps: int = 15,
    seconds: float = 8,
    max_width: int = 1280,
) -> RenderResult:
    response = await _post(
        "/render/gif",
        {
            "slides": slides_html,
            "themeCss": theme_css,
            "fps": fps,
            "seconds": seconds,
            "maxWidth": max_width,
        },
        timeout_s=900,
    )
    if response.status_code >= 400:
        raise UpstreamError(f"render-svc gif failed ({response.status_code}): {response.text[:500]}")
    data = response.json()
    try:
        content = base64.b64decode(data["gif"])
    except (KeyError, binascii.Error) as exc:
        raise UpstreamError("render-svc returned an invalid gif payload") from exc
    return RenderResult(
        content=content,
        content_type="image/gif",
        degraded=bool(data.get("degraded")),
        notes=list(data.get("notes") or []),
    )


async def render_pdf_with_notes(
    *, slides_html: list[str], theme_css: str
) -> RenderResult:
    if not slides_html:
        raise ExportDegradedError("deck has no slides to render")
    return await render_pdf(slides_html=slides_html, theme_css=theme_css)


async def render_png(slide_html: str, theme_css: str, width: int = 1280) -> bytes:
    response = await _post(
        "/render/png",
        {"slides": [slide_html], "themeCss": theme_css, "width": width},
        timeout_s=120,
    )
    if response.status_code >= 400:
        raise UpstreamError(f"render-svc png failed ({response.status_code}): {response.text[:400]}")
    data = response.json()
    return base64.b64decode(data["pngs"][0])


async def warmup() -> bool:
    url = f"{settings.render_svc_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
        return response.status_code == 200
    except (httpx.TimeoutException, httpx.TransportError):
        return False


async def wait_ready(timeout_s: float = 120) -> None:
    loops = int(timeout_s / 1.5)
    for _ in range(loops):
        if await warmup():
            return
        await asyncio.sleep(1.5)
    raise UpstreamError("render-svc did not become ready in time")