"""
Legacy Vercel /api entry (optional).

Production uses app.main:app via pyproject.toml [tool.vercel] entrypoint.
FastAPI handles /api/* and the React SPA — no vercel.json rewrites needed.
"""

from app.main import app

__all__ = ["app"]
