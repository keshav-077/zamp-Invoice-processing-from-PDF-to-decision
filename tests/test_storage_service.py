"""Tests for blob storage upload API compatibility."""

from unittest.mock import patch

import pytest

from app.config import settings
from app.storage.storage_service import BlobStorageBackend


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
