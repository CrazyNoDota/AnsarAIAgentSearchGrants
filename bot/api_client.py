"""
HTTP client for the FastAPI backend.
All business logic lives in the backend; this is a thin async HTTP client.
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

    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.post(
            "/auth/login",
            data={"username": settings.admin_username, "password": settings.admin_password},
        )
        resp.raise_for_status()
        _token_cache = resp.json()["access_token"]
        return _token_cache


async def _headers() -> dict:
    token = await _get_token()
    return {"Authorization": f"Bearer {token}"}


async def get_pending_grants(page: int = 1, size: int = 5) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get(
            "/grants",
            params={"status": "pending", "page": page, "size": size},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_grants_by_status(
    status: str,
    page: int = 1,
    size: int = 5,
    category: Optional[str] = None,
) -> dict:
    params: dict = {"status": status, "page": page, "size": size}
    if category:
        params["category"] = category
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get("/grants", params=params, headers=await _headers())
        resp.raise_for_status()
        return resp.json()


async def list_categories() -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get("/grants/categories", headers=await _headers())
        resp.raise_for_status()
        return resp.json().get("items", [])


async def search_grants(query: str, page: int = 1, size: int = 5) -> dict:
    """SQL keyword search via /grants endpoint."""
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get(
            "/grants",
            params={"search": query, "page": page, "size": size},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def hybrid_search(query: str, limit: int = 5, user_id: Optional[str] = None) -> dict:
    """Hybrid keyword + semantic search via /search endpoint."""
    params: dict = {"q": query, "limit": limit}
    if user_id:
        params["user_id"] = user_id
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=30) as client:
        resp = await client.get("/search", params=params, headers=await _headers())
        resp.raise_for_status()
        return resp.json()


async def rag_chat(query: str, limit: int = 5, user_id: Optional[str] = None) -> dict:
    """RAG chat — returns verified grants + grounded LLM response."""
    params: dict = {"q": query, "limit": limit}
    if user_id:
        params["user_id"] = user_id
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=90) as client:
        resp = await client.get("/recommendations/rag-chat", params=params, headers=await _headers())
        resp.raise_for_status()
        return resp.json()


async def review_grant(grant_id: int, decision: str, reviewer_name: str = "aydar") -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=30) as client:
        resp = await client.post(
            f"/grants/{grant_id}/review",
            json={"decision": decision, "reviewer_name": reviewer_name},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def delete_grant(grant_id: int) -> None:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.delete(
            f"/grants/{grant_id}",
            headers=await _headers(),
        )
        resp.raise_for_status()


async def get_recommendations(query: str, limit: int = 5) -> list:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=90) as client:
        resp = await client.get(
            "/recommendations",
            params={"q": query, "limit": limit},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def summarize_grant(grant_id: int) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=90) as client:
        resp = await client.get(
            f"/recommendations/{grant_id}/summarize",
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_stats() -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get("/stats", headers=await _headers())
        resp.raise_for_status()
        return resp.json()


async def get_deadlines(days: int = 30) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get(
            "/deadlines",
            params={"days": days},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_preferences() -> dict:
    """Get AI learned preferences for insights view."""
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=15) as client:
        resp = await client.get(
            "/grants/learning/preferences",
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def run_scraper() -> dict:
    """Manually trigger full scraper run."""
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=300) as client:
        resp = await client.post("/scraper/run", headers=await _headers())
        resp.raise_for_status()
        return resp.json()


# ── Subscription management ───────────────────────────────────

async def subscribe(telegram_user_id: int, telegram_chat_id: int) -> dict:
    """
    Register user for notifications.
    Called automatically on /start (saves chat_id to DB).
    This eliminates the need for a hardcoded TELEGRAM_CHAT_ID.
    """
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=10) as client:
        resp = await client.post(
            "/subscriptions/register",
            json={"telegram_user_id": telegram_user_id, "telegram_chat_id": telegram_chat_id},
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def unsubscribe(telegram_user_id: int) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=10) as client:
        resp = await client.delete(
            f"/subscriptions/unregister/{telegram_user_id}",
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def subscription_status(telegram_user_id: int) -> dict:
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=10) as client:
        resp = await client.get(
            f"/subscriptions/status/{telegram_user_id}",
            headers=await _headers(),
        )
        resp.raise_for_status()
        return resp.json()
