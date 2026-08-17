"""Tests for blob storage upload API compatibility."""

from unittest.mock import patch

import pytest

from app.config import settings
from app.storage.storage_service import BlobStorageBackend, _blob_cache_path


def test_blob_cache_path_uses_temp_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(settings, "blob_read_write_token", "token")
    path = _blob_cache_path("https://example.blob.vercel-storage.com/invoices/file.png")
    assert "invoiceflow-scratch" in str(path).replace("\\", "/")
    assert path.name.startswith("blob_")
    assert path.suffix == ".png"


@pytest.mark.asyncio
async def test_blob_get_local_path_writes_to_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.storage.storage_service._blob_cache_path",
        lambda _key: tmp_path / "cached.png",
    )
    monkeypatch.setattr(settings, "blob_read_write_token", "token")
    backend = BlobStorageBackend()
    url = "https://example.blob.vercel-storage.com/invoices/test.png"

    class FakeResp:
        content = b"png-bytes"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url):
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    path = await backend.get_local_path(url)
    assert path.parent == tmp_path
    assert path.read_bytes() == b"png-bytes"


@pytest.mark.asyncio
async def test_blob_save_upload_uses_vercel_blob_put_options(monkeypatch):
    monkeypatch.setattr(settings, "blob_read_write_token", "test-token")

    backend = BlobStorageBackend()
    captured: dict = {}

    def fake_put(path, data, options=None, timeout=10, verbose=False, multipart=False):
        captured["path"] = path
        captured["options"] = options
        captured["timeout"] = timeout
        captured["multipart"] = multipart
        return {"url": "https://example.blob.vercel-storage.com/invoices/test.png"}

    with patch("vercel_blob.put", fake_put):
        key, url = await backend.save_upload("test.png", b"data")

    assert captured["path"] == "invoices/test.png"
    assert captured["options"] == {"token": "test-token"}
    assert "access" not in (captured.get("options") or {})
    assert key == url
    assert url.startswith("https://")
