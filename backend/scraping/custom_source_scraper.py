"""
Phase 7: user-registered custom grant sources.

An operator can register an arbitrary grant/funding listing URL from the bot
(``/addsource``). This scraper fetches that page (stealth browser with plain-HTTP
fallback) and runs the ``AdaptiveParser`` over the HTML — the same
LLM-writes-a-reusable-CSS-strategy engine (cached per source; direct-LLM
extraction fallback) used for the fragile built-in sources. Extracted grants flow
into the normal ``grants`` table via the runner's ``bulk_save_grants``.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

from scraping.base_scraper import BaseScraper, GrantData
from scraping.adaptive_parser import AdaptiveParser
from core.url_guard import assert_public_url, UnsafeURLError

logger = logging.getLogger(__name__)

# Custom (operator-supplied) pages are fetched over plain HTTP with a bounded,
# SSRF-validated redirect chain — we do NOT route them through the shared stealth
# browser, and we validate every hop's host against private/reserved ranges.
_MAX_REDIRECTS = 5
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/xhtml+xml,*/*",
}


class CustomSourceScraper(BaseScraper):
    """Fetch one user-registered URL and adaptively parse grants from it."""

    # Custom pages are arbitrary; try plain HTTP first (cheap) and let the
    # adaptive parser do the heavy lifting. allow_http_fallback keeps us resilient
    # if the stealth stack is unavailable.
    stealth_default = False
    allow_http_fallback = True

    def __init__(
        self,
        source_id: int,
        url: str,
        *,
        name: Optional[str] = None,
        country: Optional[str] = None,
        parser: Optional[AdaptiveParser] = None,
    ):
        self.source_id = source_id
        self.url = url
        self.source_name = name or url
        self.country = country
        # Stable per-source cache key so a learned CSS strategy is reused across
        # runs (see AdaptiveParser / ParserCache).
        self.name = f"custom:{source_id}"
        self._parser = parser

    def _origin(self) -> str:
        """Scheme://host used to resolve root-relative links in extracted URLs."""
        p = urlparse(self.url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
        return ""

    async def _guarded_fetch(self, url: str, *, timeout: float = 45.0) -> str:
        """Fetch HTML over HTTP, validating the host (and every redirect hop)
        against private/reserved ranges to prevent SSRF."""
        current = url
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                await assert_public_url(current)
                resp = await client.get(current, headers=_DEFAULT_HEADERS)
                if resp.is_redirect and resp.next_request is not None:
                    current = str(resp.next_request.url)
                    continue
                resp.raise_for_status()
                return resp.text
        raise UnsafeURLError(f"too many redirects fetching {url!r}")

    async def scrape(self) -> list[GrantData]:
        html = await self._guarded_fetch(self.url, timeout=45.0)
        parser = self._parser or AdaptiveParser()
        owns_parser = self._parser is None
        try:
            grants = await parser.parse(
                self.name,
                html,
                default_org=self.source_name or "",
                default_country=self.country,
                base_url=self._origin(),
            )
        finally:
            # Only close the parser if we created it; a shared parser is closed by
            # the caller (the runner reuses one parser across all custom sources).
            if owns_parser:
                await parser.close()
        logger.info("[custom:%s] %s -> %d grants", self.source_id, self.url, len(grants))
        return grants
