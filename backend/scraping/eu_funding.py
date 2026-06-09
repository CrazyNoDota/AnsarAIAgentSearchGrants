"""
Scraper for the EU Funding & Tenders Portal.

Phase 1 revival: the SEDIA search API frequently returns 0 (rate-limited / bot
walled). We now:
  1. Try the public SEDIA search API over plain HTTP (fast path).
  2. If that yields 0, fetch the portal's "open calls" page through the camoufox
     stealth browser and run the adaptive LLM parser over the rendered HTML.
"""
import logging
from datetime import datetime
from typing import Optional

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

EU_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
# Human-facing open-calls listing — rendered via stealth browser on fallback.
EU_OPEN_CALLS_PAGE = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
    "opportunities/calls-for-proposals"
)


class EUFundingScraper(BaseScraper):
    name = "eu_funding"
    # API path is plain HTTP; stealth is only used on the fallback page.
    allow_http_fallback = True

    async def scrape(self) -> list[GrantData]:
        results = await self._scrape_api()
        if results:
            logger.info(f"[eu_funding] API path scraped {len(results)} grants")
            return results

        logger.warning("[eu_funding] API returned 0 — trying stealth + adaptive parser")
        return await self._scrape_stealth()

    async def _scrape_api(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            import httpx
            params = {
                "apiKey": "SEDIA",
                "text": "*",
                "pageSize": 25,
                "pageNumber": 1,
                "query": "language=en&status=31094501",  # open calls
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(EU_API_URL, params=params)
                data = resp.json() if resp.status_code == 200 else {}

            for item in data.get("results", []):
                metadata = item.get("metadata", {})
                title = self._first(metadata.get("title", []))
                url = self._first(metadata.get("callDetailsPage", []))
                if not title or not url:
                    continue
                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="European Commission",
                    description=self._first(metadata.get("callTitle", [])),
                    country="European Union",
                    region="Europe",
                    category=self._first(metadata.get("programmeName", [])),
                    deadline=self._parse_date(self._first(metadata.get("deadlineDate", []))),
                ))
        except Exception as e:
            logger.error(f"[eu_funding] API scrape failed: {e}")
        return results

    async def _scrape_stealth(self) -> list[GrantData]:
        from scraping.adaptive_parser import AdaptiveParser
        try:
            html = await self.fetch(
                EU_OPEN_CALLS_PAGE,
                stealth=True,
                wait_selector="eui-card, sedia-result-card, .eui-card",
                timeout=60,
            )
        except Exception as e:
            logger.error(f"[eu_funding] stealth fetch failed: {e}")
            return []

        parser = AdaptiveParser()
        try:
            grants = await parser.parse(
                self.name, html,
                default_org="European Commission",
                default_country="European Union",
                base_url="https://ec.europa.eu",
            )
            for g in grants:
                g.region = g.region or "Europe"
            logger.info(f"[eu_funding] stealth+adaptive scraped {len(grants)} grants")
            return grants
        finally:
            await parser.close()

    def _first(self, lst: list) -> Optional[str]:
        return lst[0] if lst else None

    def _parse_date(self, date_str: Optional[str]):
        if not date_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str[:19], fmt).date()
            except (ValueError, TypeError):
                continue
        return None
