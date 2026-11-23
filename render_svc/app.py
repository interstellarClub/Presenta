import base64
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - optional runtime dependency
    async_playwright = None  # type: ignore[assignment]

TOKEN = os.environ.get("RENDER_SVC_TOKEN", "dev-render-token")
DEFAULT_W, DEFAULT_H = 1280, 720

app = FastAPI(title="presenta-render-svc", version="0.1.0")


class RenderRequest(BaseModel):
    slides: list[str]
    themeCss: str = ""
    pageSize: str = "1280px 720px"


class GifRequest(RenderRequest):
    fps: int = 15
    seconds: float = 8
    maxWidth: int = 1280


class PngRequest(RenderRequest):
    width: int = DEFAULT_W


def _authorize(token: str | None) -> None:
    if token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid render token")


def _playwright_ready() -> bool:
    return async_playwright is not None


def _wrap_html(slides: list[str], theme_css: str) -> str:
    sections = "".join(f'<section class="page">{markup}</section>' for markup in slides)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<style>
{theme_css}
html, body {{ margin: 0; padding: 0; background: #ffffff; }}
.page {{
  width: {DEFAULT_W}px; height: {DEFAULT_H}px; overflow: hidden; position: relative;
  background: var(--color-bg, #ffffff);
  page-break-after: always; break-after: page;
}}
.page:last-child {{ page-break-after: auto; break-after: auto; }}
</style></head>
<body>{sections}</body></html>"""


async def _block_network(route) -> None:
    url = route.request.url
    if url.startswith(("data:", "about:", "blob:")):
        await route.continue_()
        return
    await route.abort()


async def _open_page(browser):
    page = await browser.new_page(viewport={"width": DEFAULT_W, "height": DEFAULT_H})
    await page.route("**/*", _block_network)
    return page


async def _launch():
    if not _playwright_ready():
        raise HTTPException(status_code=503, detail="playwright is not installed in render-svc")
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"]
    )
    return playwright, browser


def _page_size(spec: str) -> tuple[int, int]:
    match = re.match(r"^\s*(\d+)px\s+(\d+)px\s*$", spec or "")
    if not match:
        return DEFAULT_W, DEFAULT_H
    return int(match.group(1)), int(match.group(2))


def _is_dark_theme(theme_css: str) -> bool:
    match = re.search(r"--color-bg:\s*#([0-9a-fA-F]{6})", theme_css or "")
    if not match:
        return False
    value = match.group(1)
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    luminance = sum(channels) / 3
    return luminance < 0.25


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "chromium": _playwright_ready(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }


@app.post("/render/pdf")
async def render_pdf(payload: RenderRequest, x_render_token: str | None = Header(default=None)):
    _authorize(x_render_token)
    width, height = _page_size(payload.pageSize)
    notes = ["PDF 由 render-svc Chromium 直接生成，禁用 window.print"]
    playwright, browser = await _launch()
    try:
        page = await _open_page(browser)
        await page.set_content(_wrap_html(payload.slides, payload.themeCss), wait_until="load")
        pdf = await page.pdf(
            width=f"{width}px",
            height=f"{height}px",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            prefer_css_page_size=False,
        )
    finally:
        await browser.close()
        await playwright.stop()
    return {"pdf": base64.b64encode(pdf).decode("ascii"), "degraded": False, "notes": notes}


@app.post("/render/png")
async def render_png(payload: PngRequest, x_render_token: str | None = Header(default=None)):
    _authorize(x_render_token)
    playwright, browser = await _launch()
    pngs: list[str] = []
    try:
        page = await _open_page(browser)
        for markup in payload.slides:
            await page.set_content(_wrap_html([markup], payload.themeCss), wait_until="load")
            shot = await page.screenshot(type="png")
            pngs.append(base64.b64encode(shot).decode("ascii"))
    finally:
        await browser.close()
        await playwright.stop()
    return {"pngs": pngs, "degraded": False, "notes": []}


@app.post("/render/gif")
async def render_gif(payload: GifRequest, x_render_token: str | None = Header(default=None)):
    _authorize(x_render_token)
    if not payload.slides:
        raise HTTPException(status_code=400, detail="no slides to render")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise HTTPException(status_code=503, detail="ffmpeg is not installed in render-svc")
    fps = max(1, min(30, int(payload.fps)))
    seconds = max(0.5, min(30.0, float(payload.seconds)))
    notes = ["GIF 为 256 色调色板，粒子与半透明会被简化"]
    if _is_dark_theme(payload.themeCss):
        notes.append("深色主题已按浅底渲染以缓解 GIF 色带")

    playwright, browser = await _launch()
    shots: list[bytes] = []
    try:
        page = await _open_page(browser)
        for markup in payload.slides:
            await page.set_content(_wrap_html([markup], payload.themeCss), wait_until="load")
            shots.append(await page.screenshot(type="png"))
    finally:
        await browser.close()
        await playwright.stop()

    per_slide_frames = max(1, int(round(fps * seconds / max(1, len(shots)))))
    with tempfile.TemporaryDirectory(prefix="presenta-gif-") as tmp:
        directory = Path(tmp)
        index = 0
        for shot in shots:
            for _ in range(per_slide_frames):
                (directory / f"frame_{index:06d}.png").write_bytes(shot)
                index += 1
        output = directory / "out.gif"
        scale = f"scale='min({int(payload.maxWidth)},iw)':-1:flags=lanczos"
        command = [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(directory / "frame_%06d.png"),
            "-vf",
            f"{scale},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a",
            "-loop",
            "0",
            str(output),
        ]
        import asyncio

        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0 or not output.exists():
            raise HTTPException(
                status_code=500, detail=f"ffmpeg failed: {stderr.decode('utf-8', 'ignore')[:400]}"
            )
        gif = output.read_bytes()
    return {"gif": base64.b64encode(gif).decode("ascii"), "degraded": True, "notes": notes}