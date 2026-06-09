"""
Sequential scrape queue (Phase 1).

Heavy / browser-backed scrapes must NOT run via ``asyncio.gather`` over all
sources at once — on a 4 GB VPS one camoufox/Firefox session already eats
0.5-1.5 GB. This module runs registered "heavy" scrapers **strictly one at a
time** through a Redis-backed queue.

Design:
  * ``enqueue(name)`` pushes a source name onto a Redis list (the job queue).
  * ``process_queue(...)`` pops names one at a time and runs the matching
    scraper, saving results via the runner's ``bulk_save_grants`` (dedup by
    source_url stays consistent with existing behavior).
  * If Redis is unavailable, it degrades to an **in-process sequential loop**
    (still one-at-a-time) so the queue semantics hold without Redis.

GLOBAL serialization guarantee:
  An in-process ``asyncio.Lock`` only serializes a single ``process()`` loop
  inside ONE python process. Multiple API / n8n / worker invocations (separate
  processes or containers) could otherwise pop the same Redis list and run heavy
  camoufox sessions concurrently — blowing the RAM budget. To guarantee only ONE
  processor runs heavy scrapes at a time **across processes/containers**, the
  queue acquires a **Redis distributed lock** (``SET key token NX PX <ttl>``)
  before processing and releases it with a compare-and-delete Lua script so a
  slow worker can't delete a lock another worker re-acquired after a TTL expiry.
  The lock auto-expires (lease/TTL) so a crashed worker never deadlocks the
  queue. If Redis is absent we fall back to the in-process asyncio lock only and
  log that the cross-process guarantee is degraded.

Redis is configured at ``settings.redis_url`` (already in core.config).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_QUEUE_KEY = "grant_scrape:queue"
_LOCK_KEY = "grant_scrape:processor_lock"
# Lease/TTL for the distributed lock (ms). Long enough for a heavy batch of
# stealth scrapes, short enough that a crashed worker frees the queue.
_LOCK_TTL_MS = 30 * 60 * 1000  # 30 minutes
# How long to wait trying to acquire the cross-process lock before giving up.
_LOCK_ACQUIRE_TIMEOUT_S = 5.0
_LOCK_RETRY_INTERVAL_S = 0.5

# Compare-and-delete: only release the lock if we still own it (token matches).
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# Secondary in-process guard: serializes process() loops within ONE process.
_PROCESS_LOCK = asyncio.Lock()


class ScrapeQueue:
    """Redis-backed FIFO of scraper names, processed sequentially."""

    def __init__(self) -> None:
        self._redis = None
        self._local: list[str] = []
        self._lock_token: Optional[str] = None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception as e:  # pragma: no cover
            logger.info("ScrapeQueue: Redis unavailable (%s); in-process queue", e)
            self._redis = None

    async def enqueue(self, name: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.rpush(_QUEUE_KEY, name)
                return
            except Exception as e:
                logger.warning("ScrapeQueue enqueue redis failed (%s); local", e)
        self._local.append(name)

    async def _pop(self) -> Optional[str]:
        if self._redis is not None:
            try:
                return await self._redis.lpop(_QUEUE_KEY)
            except Exception as e:
                logger.warning("ScrapeQueue pop redis failed (%s); local", e)
        return self._local.pop(0) if self._local else None

    async def _acquire_distributed_lock(self) -> bool:
        """Acquire the cross-process Redis lock. Returns True if held.

        Uses ``SET key token NX PX ttl`` with a unique token so only one
        processor across all processes/containers runs heavy scrapes at once.
        The TTL means a crashed worker's lock auto-expires. Returns False (and
        logs a degraded-guarantee warning) if Redis is absent.
        """
        if self._redis is None:
            logger.warning(
                "ScrapeQueue: no Redis — cross-process lock unavailable; relying "
                "on in-process lock only (cross-process guarantee DEGRADED)"
            )
            return False
        token = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _LOCK_ACQUIRE_TIMEOUT_S
        while True:
            try:
                ok = await self._redis.set(
                    _LOCK_KEY, token, nx=True, px=_LOCK_TTL_MS
                )
            except Exception as e:
                logger.warning(
                    "ScrapeQueue: distributed lock SET failed (%s); cross-process "
                    "guarantee DEGRADED (in-process lock only)", e
                )
                return False
            if ok:
                self._lock_token = token
                logger.info("[scrape_queue] acquired distributed processor lock")
                return True
            if loop.time() >= deadline:
                logger.warning(
                    "[scrape_queue] another processor holds the lock; skipping this "
                    "run to preserve the one-at-a-time cross-process guarantee"
                )
                return False
            await asyncio.sleep(_LOCK_RETRY_INTERVAL_S)

    async def _release_distributed_lock(self) -> None:
        """Release the Redis lock iff we still own it (compare-and-del)."""
        if self._redis is None or self._lock_token is None:
            return
        try:
            await self._redis.eval(_RELEASE_LUA, 1, _LOCK_KEY, self._lock_token)
        except Exception as e:
            logger.warning("ScrapeQueue: distributed lock release failed (%s)", e)
        finally:
            self._lock_token = None

    async def process(
        self,
        run_one: Callable[[str], Awaitable[tuple[str, list, Optional[str]]]],
    ) -> list[tuple[str, list, Optional[str]]]:
        """Pop and run jobs ONE AT A TIME. ``run_one`` runs a single scraper by
        name and returns ``(name, grants, error)``. Returns all results.

        Serialization is enforced at two levels:
          1. A Redis distributed lock — the real GLOBAL (cross-process) guarantee.
             If another processor already holds it, this run returns immediately
             with no results (its jobs stay queued for the active processor).
          2. An in-process asyncio lock — a secondary guard so two ``process()``
             loops in the SAME process can't interleave.
        """
        # 1. Cross-process guarantee (the real one). If we can't get it because
        #    another processor is active, bail out — those jobs are already on
        #    the shared queue and will be drained by the holder.
        have_dist_lock = await self._acquire_distributed_lock()
        if self._redis is not None and not have_dist_lock:
            return []

        # 2. In-process secondary guard.
        async with _PROCESS_LOCK:
            try:
                return await self._drain(run_one)
            finally:
                await self._release_distributed_lock()

    async def _drain(
        self,
        run_one: Callable[[str], Awaitable[tuple[str, list, Optional[str]]]],
    ) -> list[tuple[str, list, Optional[str]]]:
        results: list[tuple[str, list, Optional[str]]] = []
        while True:
            name = await self._pop()
            if name is None:
                break
            logger.info("[scrape_queue] processing %s", name)
            try:
                results.append(await run_one(name))
            except Exception as e:  # never let one job kill the queue
                logger.error("[scrape_queue] %s crashed: %s", name, e)
                results.append((name, [], f"[{name}] {e.__class__.__name__}: {e}"))
        return results

    async def close(self) -> None:
        # Defensive: drop the lock if a caller forgot (process() releases it).
        await self._release_distributed_lock()
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
