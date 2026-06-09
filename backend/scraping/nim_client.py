"""
NVIDIA NIM Chat Completions client (Phase 1).

Phase 0 proved that Webwright cannot drive NIM (Webwright speaks the OpenAI
*Responses* API; NIM only exposes *Chat Completions*). So for the "LLM writes the
parser" loop we call NIM Chat Completions **directly** via the same `openai`
AsyncOpenAI client the rest of the repo already uses (see
``scraping/ai_search_agent.py`` and ``services/ai_service.py``).

This is a thin wrapper so the adaptive-parser loop doesn't re-implement client
setup. Keys are loaded from settings/.env (never hardcoded).
"""
from __future__ import annotations

import logging
from typing import Optional

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 480B model first-token latency can exceed 60s (Phase 0 finding) — use a
# generous timeout for the parser-generation calls.
DEFAULT_TIMEOUT_S = 120


class NIMClient:
    """Minimal NVIDIA NIM Chat Completions wrapper."""

    def __init__(self) -> None:
        self._client = None
        if settings.nvidia_api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    base_url=settings.nvidia_base_url,
                    api_key=settings.nvidia_api_key,
                )
            except Exception as e:  # pragma: no cover
                logger.warning("NIM client init failed: %s", e)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def chat(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2500,
        timeout: int = DEFAULT_TIMEOUT_S,
    ) -> Optional[str]:
        """Single-turn Chat Completions call. Returns the text reply or None."""
        if not self._client:
            return None
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = await self._client.chat.completions.create(
                model=settings.nvidia_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error("NIM chat call failed: %s", e)
            return None
