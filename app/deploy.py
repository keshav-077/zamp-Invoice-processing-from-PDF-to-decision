"""
Deployment readiness checks for Vercel / production.

Used by /api/health and startup logging — not a hard gate in dev.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class DeployCheck:
    name: str
    ok: bool
    required: bool
    detail: str


@dataclass
class DeployReport:
    platform: str
    ready: bool
    checks: list[DeployCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "ready": self.ready,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "required": c.required,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
            "warnings": self.warnings,
        }


def is_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def is_production_runtime() -> bool:
    return is_vercel() or os.environ.get("VERCEL_ENV") in ("production", "preview")


def evaluate_deploy_readiness() -> DeployReport:
    """Return deploy checklist for health endpoint and ops."""
    platform = "vercel" if is_vercel() else "local"
    checks: list[DeployCheck] = []

    has_llm = bool(settings.gemini_api_key or settings.groq_api_key or settings.openrouter_api_key)
    checks.append(
        DeployCheck(
            name="llm_provider",
            ok=has_llm,
            required=True,
            detail="At least one LLM API key configured",
        )
    )

    has_postgres = bool(settings.database_url)
    checks.append(
        DeployCheck(
            name="database",
            ok=has_postgres or not is_vercel(),
            required=is_vercel(),
            detail=(
                "Postgres DATABASE_URL configured"
                if has_postgres
                else ("SQLite (local only)" if not is_vercel() else "DATABASE_URL required on Vercel")
            ),
        )
    )

    has_blob = bool(settings.blob_read_write_token)
    checks.append(
        DeployCheck(
            name="blob_storage",
            ok=has_blob or not is_vercel(),
            required=is_vercel(),
            detail=(
                "Vercel Blob configured"
                if has_blob
                else ("Local uploads/" if not is_vercel() else "BLOB_READ_WRITE_TOKEN required on Vercel")
            ),
        )
    )

    has_inngest = bool(settings.inngest_event_key and settings.inngest_signing_key)
    checks.append(
        DeployCheck(
            name="inngest",
            ok=has_inngest or not is_vercel(),
            required=False,
            detail=(
                "Inngest async jobs configured"
                if has_inngest
                else "Optional — background tasks used as fallback (300s limit)"
            ),
        )
    )

    warnings: list[str] = []
    if is_vercel() and not has_inngest:
        warnings.append(
            "INNGEST keys not set — jobs run via serverless background tasks (max 300s per invoice)."
        )
    if is_vercel() and not has_postgres:
        warnings.append("SQLite on Vercel is ephemeral — set DATABASE_URL (Neon Postgres).")
    if is_vercel() and not has_blob:
        warnings.append("Uploads will not persist — set BLOB_READ_WRITE_TOKEN.")

    required_ok = all(c.ok for c in checks if c.required)
    return DeployReport(
        platform=platform,
        ready=required_ok and has_llm,
        checks=checks,
        warnings=warnings,
    )
