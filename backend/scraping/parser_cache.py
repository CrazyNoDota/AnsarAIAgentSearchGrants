"""
Parser-strategy cache (Phase 1).

Caches LLM-generated extraction strategies keyed by source so the adaptive
parser doesn't regenerate a parser on every run. Backed by Redis (the repo
already configures ``settings.redis_url``); if Redis is unreachable it falls
back to a local JSON file so the loop still works offline / in tests.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_KEY_PREFIX = "grant_parser:"
# Generated parsers are reusable but pages drift — re-learn after 30 days.
_TTL_SECONDS = 30 * 24 * 3600

_DEFAULT_FALLBACK_DIR = str(Path(__file__).parent / "_parser_cache")


def _fallback_dir() -> Path:
    # Resolved per-call so PARSER_CACHE_DIR can be overridden at runtime (tests).
    return Path(os.getenv("PARSER_CACHE_DIR", _DEFAULT_FALLBACK_DIR))


def _fallback_path(source: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source)
    return _fallback_dir() / f"{safe}.json"


class ParserCache:
    """Get/set extraction strategies keyed by source name."""

    def __init__(self) -> None:
        self._redis = None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception as e:  # pragma: no cover
            logger.info("ParserCache: Redis unavailable (%s); using file fallback", e)
            self._redis = None

    async def get(self, source: str) -> Optional[dict]:
        # Try Redis first
        if self._redis is not None:
            try:
                raw = await self._redis.get(_KEY_PREFIX + source)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning("ParserCache redis get failed (%s); file fallback", e)
        # File fallback
        path = _fallback_path(source)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("_expires_at", 0) > time.time():
                    return data.get("strategy")
            except Exception:
                pass
        return None

    async def set(self, source: str, strategy: dict) -> None:
        payload = json.dumps(strategy)
        if self._redis is not None:
            try:
                await self._redis.set(_KEY_PREFIX + source, payload, ex=_TTL_SECONDS)
                return
            except Exception as e:
                logger.warning("ParserCache redis set failed (%s); file fallback", e)
        # File fallback
        try:
            _fallback_dir().mkdir(parents=True, exist_ok=True)
            _fallback_path(source).write_text(
                json.dumps({"strategy": strategy, "_expires_at": time.time() + _TTL_SECONDS}),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("ParserCache file set failed: %s", e)

    async def invalidate(self, source: str) -> None:
        """Delete a cached strategy for ``source`` (both Redis and file fallback).

        Called when a cached strategy returns 0 grants (page drifted) so the bad
        strategy doesn't persist and force the same dead cache path + LLM call on
        every later run.
        """
        if self._redis is not None:
            try:
                await self._redis.delete(_KEY_PREFIX + source)
            except Exception as e:
                logger.warning("ParserCache redis invalidate failed (%s)", e)
        path = _fallback_path(source)
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning("ParserCache file invalidate failed: %s", e)

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
