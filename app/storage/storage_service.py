"""Document storage abstraction — local filesystem or Vercel Blob."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    async def save_upload(self, filename: str, content: bytes) -> tuple[str, str]:
        """Save file; return (storage_key, public_url)."""

    @abstractmethod
    async def get_local_path(self, storage_key: str) -> Path:
        """Return a local path for pipeline processing (may download from blob)."""

    @abstractmethod
    def public_url(self, storage_key: str) -> str:
        """Return URL for browser preview."""


class LocalStorageBackend(StorageBackend):
    async def save_upload(self, filename: str, content: bytes) -> tuple[str, str]:
        upload_dir = settings.upload_path
        upload_dir.mkdir(parents=True, exist_ok=True)
        key = filename
        path = upload_dir / key
        path.write_bytes(content)
        return key, f"/uploads/{key}"

    async def get_local_path(self, storage_key: str) -> Path:
        return settings.upload_path / storage_key

    def public_url(self, storage_key: str) -> str:
        return f"/uploads/{storage_key}"


class BlobStorageBackend(StorageBackend):
    async def save_upload(self, filename: str, content: bytes) -> tuple[str, str]:
        try:
            from vercel_blob import put
        except ImportError as exc:
            raise RuntimeError("vercel-blob package required for blob storage") from exc

        if not settings.blob_read_write_token:
            raise RuntimeError("BLOB_READ_WRITE_TOKEN not configured")

        path = f"invoices/{filename}"
        options = {"token": settings.blob_read_write_token}
        timeout = max(60, min(settings.upload_api_timeout_seconds, 300))

        blob = put(
            path,
            content,
            options=options,
            timeout=timeout,
            multipart=len(content) > 4 * 1024 * 1024,
        )
        url = blob.get("url") or blob.get("downloadUrl") or ""
        if not url:
            raise RuntimeError(f"Vercel Blob upload returned no URL: {blob!r}")

        logger.info("Uploaded to Vercel Blob: %s", url)
        # Store the public URL as the key so downstream download works on Vercel.
        return url, url

    async def get_local_path(self, storage_key: str) -> Path:
        import httpx

        tmp = settings.upload_path / f"_blob_{storage_key.replace('/', '_')}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if storage_key.startswith("http"):
            url = storage_key
        else:
            url = self.public_url(storage_key)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            tmp.write_bytes(resp.content)
        return tmp

    def public_url(self, storage_key: str) -> str:
        if storage_key.startswith("http"):
            return storage_key
        return storage_key


def get_storage() -> StorageBackend:
    if settings.blob_read_write_token:
        return BlobStorageBackend()
    return LocalStorageBackend()
