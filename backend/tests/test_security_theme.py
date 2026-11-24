import io
import json
import zipfile

import pytest
from httpx import AsyncClient

from app.core.security import (
    hash_password,
    invite_code_hash,
    new_opaque_token,
    normalize_invite_code,
    token_digest,
    verify_password,
)
from app.services.theme.manifest import contrast_ratio, load_all_builtin, wcag_report


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("presenta12345")
    assert hashed.startswith("$argon2id$")
    assert verify_password("presenta12345", hashed)
    assert not verify_password("wrong-password", hashed)


def test_token_and_invite_helpers() -> None:
    token = new_opaque_token(32)
    assert token_digest(token) != token
    assert len(token_digest(token)) == 64
    assert normalize_invite_code("ab12-cd34") == "AB12CD34"
    assert invite_code_hash("ab12-cd34") == invite_code_hash("AB12 CD34")
    assert invite_code_hash("AAAA") != invite_code_hash("BBBB")


def test_builtin_themes_pass_contrast_and_manifest_rules() -> None:
    manifests = load_all_builtin()
    assert {manifest["id"] for manifest in manifests} == {
        "academic",
        "pitch",
        "lecture",
        "launch",
        "tech",
        "minimal",
    }
    for manifest in manifests:
        report = wcag_report(manifest)
        assert report["checks"], manifest["id"]
        for check in report["checks"]:
            assert check["ratio"] >= 4.5, f"{manifest['id']} {check}"
        assert manifest["fonts"]["version"] == "1"


def test_contrast_ratio_extremes() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") > 20
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == 1.0


async def test_theme_pack_upload(
    client: AsyncClient,
    invited_user: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.api.routers import themes as themes_router

    monkeypatch.setattr(themes_router, "_MANIFEST_DIR", tmp_path)
    manifest = load_all_builtin()[0]
    manifest["name"] = "自定义验收主题"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("tokens.css", ":root { --color-primary: #1F4E79; }")
    response = await client.post(
        "/api/themes",
        files={"file": ("theme.zip", buffer.getvalue(), "application/zip")},
        data={"name": "自定义验收主题"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "自定义验收主题"
    assert response.json()["id"].startswith("custom-")
