from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class GrantData:
    """Standardized grant data returned by all scrapers."""
    title: str
    source_url: str
    organization: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[date] = None
    # Phase 1 structured filter fields (optional; persisted by the runner).
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    currency: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    grant_amount: Optional[str] = None


class BaseScraper(ABC):
    """Abstract base class for all grant scrapers.

    Phase 1 adds an opt-in *stealth* fetch path: a scraper can call
    ``self.fetch(url, stealth=True)`` to render a page through the camoufox
    anti-detect browser (one session at a time, torn down after each fetch),
    falling back to plain HTTP when stealth is unavailable. The default
    ``stealth_default`` flag lets a scraper subclass opt-in wholesale.
    """

    name: str = "base"
    # When True, ``fetch`` uses the stealth browser by default.
    stealth_default: bool = False
    # Whether plain-HTTP should be tried if stealth is unavailable.
    allow_http_fallback: bool = True

    @abstractmethod
    async def scrape(self) -> list[GrantData]:
        """Run the scraper and return a list of GrantData objects."""
        ...

    def normalize_url(self, url: str, base: str = "") -> str:
        """Ensure URL is absolute."""
        if url.startswith("http"):
            return url
        return base.rstrip("/") + "/" + url.lstrip("/")

    async def fetch(
        self,
        url: str,
        *,
        stealth: Optional[bool] = None,
        wait_selector: Optional[str] = None,
        timeout: float = 30.0,
        headers: Optional[dict] = None,
    ) -> str:
        """Fetch a URL's HTML.

        If ``stealth`` (or ``self.stealth_default``) is set, render via the
        camoufox stealth browser. If stealth is unavailable in this environment
        and ``allow_http_fallback`` is True, transparently fall back to plain
        httpx. Returns the response/page body as text.
        """
        use_stealth = self.stealth_default if stealth is None else stealth

        if use_stealth:
            import logging
            log = logging.getLogger(__name__)
            from scraping.stealth_browser import fetch_html, StealthUnavailable
            try:
                return await fetch_html(
                    url,
                    wait_selector=wait_selector,
                    timeout_ms=int(timeout * 1000),
                )
            except StealthUnavailable as e:
                # Stealth stack not installed/fetched in this environment.
                if not self.allow_http_fallback:
                    raise
                log.warning(
                    "[%s] stealth unavailable (%s); falling back to HTTP for %s",
                    self.name, e, url,
                )
            except (KeyboardInterrupt, SystemExit, MemoryError):
                # Never swallow these — let them propagate.
                raise
            except Exception as e:
                # Real stealth runtime failure: navigation timeout, page/browser
                # crash, camoufox/Playwright runtime error. Degrade to the cheap
                # HTTP path instead of returning nothing. Log with context (and
                # the traceback) so a genuine programming error is still visible.
                if not self.allow_http_fallback:
                    raise
                log.warning(
                    "[%s] stealth runtime error (%s: %s); falling back to HTTP for %s",
                    self.name, e.__class__.__name__, e, url, exc_info=True,
                )

        import httpx
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json,application/xhtml+xml,*/*",
        }
        if headers:
            default_headers.update(headers)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=default_headers)
            resp.raise_for_status()
            return resp.text
