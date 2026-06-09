"""
Green Climate Fund (GCF) — funding opportunities / Requests for Proposals.

New in Phase 1. GCF publishes RFPs and funding windows on greenclimate.fund.
The site is JS-heavy and bot-walled, so this scraper goes stealth-first:

  1. Try the GCF open-data RFP JSON endpoint over plain HTTP (fast path, if up).
  2. Otherwise render the RFP listing page through the camoufox stealth browser
     and run the adaptive LLM parser over it.

Dedup stays by source_url (handled by the runner's bulk_save_grants).
"""
import logging
from datetime import datetime
from typing import Optional

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

# GCF Requests for Proposals listing (human page).
GCF_RFP_PAGE = "https://www.greenclimate.fund/about/partners/rfp"
# Open-data style JSON sometimes served by the site CMS (best-effort fast path).
GCF_API = "https://www.greenclimate.fund/api/rfp"


class GCFScraper(BaseScraper):
    name = "gcf_grants"
    # GCF is bot-walled; default to stealth, but allow HTTP fallback for the API.
    stealth_default = False
    allow_http_fallback = True

    async def scrape(self) -> list[GrantData]:
        results = await self._scrape_api()
        if results:
            logger.info(f"[gcf_grants] API path scraped {len(results)} grants")
            return results

        logger.warning("[gcf_grants] API returned 0 — trying stealth + adaptive parser")
        return await self._scrape_stealth()

    async def _scrape_api(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(GCF_API, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    return []
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype:
                    return []
                data = resp.json()
            items = data if isinstance(data, list) else (
                data.get("items") or data.get("results") or data.get("data") or []
            )
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or item.get("name") or "").strip()
                url = (item.get("url") or item.get("link") or "").strip()
                if not title or not url:
                    continue
                results.append(GrantData(
                    title=title[:512],
                    source_url=url,
                    organization="Green Climate Fund",
                    description=(item.get("summary") or item.get("description") or "")[:1500],
                    country="International",
                    region="Global",
                    category="Climate",
                    industry="Climate / Green Energy",
                    deadline=self._parse_date(item.get("deadline") or item.get("closing_date")),
                ))
        except Exception as e:
            logger.error(f"[gcf_grants] API scrape failed: {e}")
        return results

    async def _scrape_stealth(self) -> list[GrantData]:
        from scraping.adaptive_parser import AdaptiveParser
        try:
            html = await self.fetch(GCF_RFP_PAGE, stealth=True, timeout=60)
        except Exception as e:
            logger.error(f"[gcf_grants] stealth fetch failed: {e}")
            return []

        parser = AdaptiveParser()
        try:
            grants = await parser.parse(
                self.name, html,
                default_org="Green Climate Fund",
                default_country="International",
                base_url="https://www.greenclimate.fund",
            )
            for g in grants:
                g.region = g.region or "Global"
                g.category = g.category or "Climate"
                g.industry = g.industry or "Climate / Green Energy"
            logger.info(f"[gcf_grants] stealth+adaptive scraped {len(grants)} grants")
            return grants
        finally:
            await parser.close()

    def _parse_date(self, value) -> Optional[datetime.date]:
        if not value:
            return None
        s = str(value)[:19]
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d %B %Y"):
            try:
                return datetime.strptime(s[:len(fmt) + 4], fmt).date()
            except (ValueError, TypeError):
                continue
        return None
