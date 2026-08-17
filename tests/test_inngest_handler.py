"""Tests for Inngest job scheduling fallbacks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.jobs import inngest_handler


@pytest.fixture(autouse=True)
def reset_inngest_state():
    inngest_handler._inngest_client = None
    inngest_handler._inngest_disabled = False
    yield
    inngest_handler._inngest_client = None
    inngest_handler._inngest_disabled = False


@pytest.mark.asyncio
async def test_schedule_falls_back_when_inngest_send_fails(monkeypatch):
    monkeypatch.setattr(settings, "inngest_event_key", "bad-key")
    monkeypatch.setattr(settings, "inngest_signing_key", "signing-key")

    mock_client = MagicMock()
    mock_client.send = AsyncMock(side_effect=RuntimeError("Event key not found"))
    monkeypatch.setattr(inngest_handler, "get_inngest", lambda: mock_client)

    bg = MagicMock()
    with patch.object(inngest_handler, "run_job", new=AsyncMock()):
        mode = await inngest_handler.schedule_invoice_job("JOB-TEST", background_tasks=bg)

    assert mode == "background"
    bg.add_task.assert_called_once()


def test_inngest_not_configured_with_event_key_only(monkeypatch):
    monkeypatch.setattr(settings, "inngest_event_key", "only-event-key")
    monkeypatch.setattr(settings, "inngest_signing_key", "")
    assert inngest_handler.get_inngest() is None
