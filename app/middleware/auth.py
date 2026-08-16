"""Clerk JWT verification and optional auth dependency."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)


async def optional_auth(request: Request) -> dict | None:
    """Verify Clerk JWT when configured; otherwise allow anonymous (local dev)."""
    if not settings.clerk_jwt_issuer:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    try:
        import httpx
        import jwt
        from jwt import PyJWKClient

        jwks_url = f"{settings.clerk_jwt_issuer}/.well-known/jwks.json"
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_jwt_issuer,
        )
        return payload
    except Exception as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc


AuthUser = Annotated[dict | None, Depends(optional_auth)]
