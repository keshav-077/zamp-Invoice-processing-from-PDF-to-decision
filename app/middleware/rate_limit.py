"""Upstash Redis rate limiting."""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)


async def rate_limit(request: Request, bucket: str = "default", limit: int = 30, window_s: int = 60) -> None:
    """Apply rate limit when Upstash is configured."""
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        return

    client_ip = request.client.host if request.client else "unknown"
    key = f"rl:{bucket}:{client_ip}:{int(time.time()) // window_s}"

    try:
        import httpx

        url = f"{settings.upstash_redis_rest_url}/incr/{key}"
        headers = {"Authorization": f"Bearer {settings.upstash_redis_rest_token}"}
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            count = int(resp.json().get("result", 0))
            if count == 1:
                expire_url = f"{settings.upstash_redis_rest_url}/expire/{key}/{window_s}"
                await client.post(expire_url, headers=headers)
            if count > limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Rate limit check failed (allowing request): %s", exc)
