"""Tests for deployment readiness checks."""

from app.deploy import evaluate_deploy_readiness, is_vercel


def test_local_deploy_report(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    report = evaluate_deploy_readiness()
    assert report.platform == "local"
    assert report.to_dict()["platform"] == "local"


def test_vercel_requires_postgres_and_blob(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.config import settings

    settings.gemini_api_key = "test-key"
    settings.database_url = ""
    settings.blob_read_write_token = ""
    report = evaluate_deploy_readiness()
    assert report.platform == "vercel"
    assert report.ready is False
    names = {c.name for c in report.checks if c.required and not c.ok}
    assert "database" in names
    assert "blob_storage" in names


def test_is_vercel_helper(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert is_vercel() is True
