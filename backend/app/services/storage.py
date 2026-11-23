import asyncio
import hashlib
import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles
import boto3
from botocore.client import Config

from app.core.config import settings
from app.core.errors import NotFoundError


def safe_key(prefix: str, suffix: str = "") -> str:
    clean_prefix = re.sub(r"[^a-zA-Z0-9/_-]", "", prefix).strip("/")
    clean_suffix = re.sub(r"[^a-zA-Z0-9.]", "", suffix).lower()[:12]
    return f"{clean_prefix}/{uuid4().hex}{('.' + clean_suffix) if clean_suffix else ''}"


def guess_content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class LocalStorage:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise NotFoundError("invalid storage key")
        return path

    async def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as handle:
            await handle.write(data)
        return key

    async def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise NotFoundError("object not found")
        async with aiofiles.open(path, "rb") as handle:
            return await handle.read()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def size(self, key: str) -> int:
        path = self._path(key)
        return path.stat().st_size if path.exists() else 0

    async def url_for(self, key: str, ttl_s: int | None = None) -> str:
        return f"{settings.api_prefix}/assets/{key}"

    async def copy_to(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), destination)
        return destination


class S3Storage:
    backend = "s3"

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_key,
            aws_secret_access_key=settings.s3_secret,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        def _put() -> None:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type or guess_content_type(key),
            )

        await asyncio.to_thread(_put)
        return key

    async def get_bytes(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            raise NotFoundError("object not found") from exc

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def size(self, key: str) -> int:
        def _head() -> int:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

        return await asyncio.to_thread(_head)

    async def url_for(self, key: str, ttl_s: int | None = None) -> str:
        ttl = ttl_s or settings.download_url_ttl_s

        def _sign() -> str:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=ttl,
            )

        return await asyncio.to_thread(_sign)

    async def copy_to(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = await self.get_bytes(key)
        async with aiofiles.open(destination, "wb") as handle:
            await handle.write(data)
        return destination


def _build_storage() -> LocalStorage | S3Storage:
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.local_storage_dir)


storage = _build_storage()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_dict() -> dict[str, Any]:
    return {"backend": storage.backend}