"""
Stealth browser worker (Phase 1).

A reusable, memory-conscious stealth-fetch layer for fragile sources that block
plain HTTP scrapers. Uses **camoufox** (anti-detect Firefox) driven through
Playwright. Designed for a 4 GB VPS:

  * ONE browser session at a time (a module-level asyncio.Lock serializes launches).
  * The browser is launched on demand and **torn down after each fetch task** —
    we never keep a Firefox resident between scrapes (RAM budget: camoufox eats
    0.5-1.5 GB per session per the infra plan).
  * Graceful degradation: if the `camoufox` pip package or its patched Firefox
    binary isn't present in this environment, `fetch()` raises
    ``StealthUnavailable`` instead of crashing the import. Callers (base_scraper)
    fall back to plain HTTP. On the VPS, run ``python -m camoufox fetch`` once to
    download the patched Firefox and the real launch path activates.

This module imports cleanly even when camoufox/playwright are NOT installed —
the heavy imports happen lazily inside ``fetch``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Serialize browser launches process-wide so we never run two Firefox
# instances concurrently (RAM cap mindset for the 4 GB VPS).
_BROWSER_LOCK = asyncio.Lock()

# Default per-page timeout (ms). Stealth pages can be slow behind bot walls.
DEFAULT_TIMEOUT_MS = 45_000


class StealthUnavailable(RuntimeError):
    """Raised when the stealth browser stack can't run in this environment."""


def stealth_available() -> bool:
    """Return True if the camoufox pip package is importable.

    NOTE: this does NOT guarantee the patched Firefox binary is fetched — that
    only surfaces at launch time. Use this as a cheap pre-check; ``fetch`` does
    the authoritative check and raises ``StealthUnavailable`` if the binary is
    missing.
    """
    try:
        import camoufox  # noqa: F401
        return True
    except Exception:
        return False


async def fetch_html(
    url: str,
    *,
    wait_selector: Optional[str] = None,
    wait_until: str = "domcontentloaded",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    extra_wait_ms: int = 0,
) -> str:
    """Fetch a URL through the stealth browser and return the rendered HTML.

    One browser per call, torn down before returning. Serialized by a global
    lock so only one Firefox runs at a time.

    Raises:
        StealthUnavailable: camoufox/playwright not installed, or the patched
            Firefox binary isn't fetched (run ``python -m camoufox fetch``).
    """
    try:
        from camoufox.async_api import AsyncCamoufox
    except Exception as e:  # pragma: no cover - depends on VPS install
        raise StealthUnavailable(
            "camoufox is not importable; run "
            "`pip install camoufox[geoip]` then `python -m camoufox fetch`"
        ) from e

    async with _BROWSER_LOCK:
        browser = None
        try:
            # headless=True + humanize gives us anti-detect defaults.
            # We pass os/locale through camoufox's own fingerprint engine.
            cm = AsyncCamoufox(headless=True, humanize=True)
            try:
                browser = await cm.__aenter__()
            except Exception as e:  # binary missing / launch failure
                raise StealthUnavailable(
                    f"camoufox failed to launch (patched Firefox likely not "
                    f"fetched — run `python -m camoufox fetch`): {e}"
                ) from e

            page = await browser.new_page()
            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=timeout_ms)
                    except Exception:
                        logger.warning(
                            "[stealth] selector %r not found on %s (continuing)",
                            wait_selector, url,
                        )
                if extra_wait_ms:
                    await page.wait_for_timeout(extra_wait_ms)
                html = await page.content()
                logger.info("[stealth] fetched %s (%d bytes)", url, len(html))
                return html
            finally:
                await page.close()
        finally:
            # Always tear the browser fully down — no resident sessions.
            if browser is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    logger.warning("[stealth] teardown error for %s", url, exc_info=True)


async def fetch_json_via_browser(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> str:
    """Fetch a JSON endpoint through the stealth browser (some portals gate
    their JSON APIs behind the same bot wall as the HTML). Returns the raw body
    text of the page, which the caller can json.loads().
    """
    html = await fetch_html(url, wait_until="domcontentloaded", timeout_ms=timeout_ms)
    # Firefox wraps raw JSON in a <pre> when rendering application/json. Strip the
    # most common wrappers; callers should still defensively json.loads().
    body = html
    lower = body.lower()
    if "<pre" in lower:
        start = body.find(">", lower.find("<pre")) + 1
        end = lower.rfind("</pre>")
        if 0 < start < end:
            body = body[start:end]
    # Unescape minimal HTML entities Firefox injects into the <pre> view.
    return (
        body.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .strip()
    )
