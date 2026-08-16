"""
Vercel serverless entry point for FastAPI.

Vercel routes /api/* here. The app instance is imported from app.main.
"""

from app.main import app

__all__ = ["app"]
