"""
HTTP client for the FastAPI backend.
The bot acts as a thin client — all logic lives in the backend.
"""
import logging
from typing import Optional

import httpx

from config import get_bot_settings

logger = logging.getLogger(__name__)
settings = get_bot_settings()

_token_cache: Optional[str] = None


async def _get_token() -> str:
    """Authenticate with backend and cache JWT token."""
    global _token_cache
    if _token_cache:
        return _token_cache

    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.post(
            "/auth/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
        )
        resp.raise_for_status()
        _token_cache = resp.json()["access_token"]
        return _token_cache


async def _headers() -> dict:
    token = await _get_token()
    return {"Authorization": f"Bearer {token}"}


async def get_pending_grants(page: int = 1, size: int = 5) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.get(
            "/grants",
            params={"status": "pending", "page": page, "size": size},
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def get_grants_by_status(status: str, page: int = 1, size: int = 5) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.get(
            "/grants",
            params={"status": status, "page": page, "size": size},
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def search_grants(query: str, page: int = 1, size: int = 5) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.get(
            "/grants",
            params={"search": query, "page": page, "size": size},
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def review_grant(grant_id: int, decision: str, reviewer_name: str = "telegram_staff") -> dict:
    """Submit approve/reject decision to backend."""
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.post(
            f"/grants/{grant_id}/review",
            json={"decision": decision, "reviewer_name": reviewer_name},
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_grant(grant_id: int) -> None:
    """Permanently remove a grant from the backend."""
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.delete(
            f"/grants/{grant_id}",
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()


async def get_recommendations(query: str, limit: int = 5) -> list:
    # LLM ranking + DB scan can take a while.
    # api/index.py maxDuration is 90s; api/telegram.py is 60s — stay under
    # the webhook function budget so we never get killed mid-flight.
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=55) as client:
        resp = await client.get(
            "/recommendations",
            params={"q": query, "limit": limit},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def summarize_grant(grant_id: int) -> dict:
    """Generate AI summary for a specific grant using Qwen3-480B."""
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=55) as client:
        resp = await client.get(
            f"/recommendations/{grant_id}/summarize",
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_stats() -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url) as client:
        resp = await client.get(
            "/stats",
            headers=await _headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
