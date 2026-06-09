"""
Scraper for UNDP procurement / grant notices.

Phase 1 revival: the legacy RSS feed (procurement-notices.undp.org ...view=RSS)
is unreliable and often returns nothing. We now:
  1. Try the RSS feed over plain HTTP (fast path).
  2. If that yields 0, render the UNDP procurement listing through the camoufox
     stealth browser and run the adaptive LLM parser over it.
"""
import asyncio
import logging
from typing import Optional

import feedparser

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

UNDP_RSS = "https://procurement-notices.undp.org/index.cfm?view=RSS"
UNDP_LISTING = "https://procurement-notices.undp.org/"


class UNDPScraper(BaseScraper):
    name = "undp_grants"

    async def scrape(self) -> list[GrantData]:
        results = await self._scrape_rss()
        if results:
            logger.info(f"[undp_grants] RSS scraped {len(results)} grants")
            return results

        logger.warning("[undp_grants] RSS returned 0 — trying stealth + adaptive parser")
        return await self._scrape_stealth()

    async def _scrape_rss(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, UNDP_RSS)
            for entry in feed.entries[:25]:
                title = entry.get("title", "")
                url = entry.get("link", "")
                if not title or not url:
                    continue
                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="UNDP",
                    description=entry.get("summary", ""),
                    country=self._extract_country(title),
                    region="Global",
                    category="International Development",
                    deadline=None,
                ))
        except Exception as e:
            logger.error(f"[undp_grants] RSS scrape failed: {e}")
        return results

    async def _scrape_stealth(self) -> list[GrantData]:
        from scraping.adaptive_parser import AdaptiveParser
        try:
            html = await self.fetch(UNDP_LISTING, stealth=True, timeout=60)
        except Exception as e:
            logger.error(f"[undp_grants] stealth fetch failed: {e}")
            return []

        parser = AdaptiveParser()
        try:
            grants = await parser.parse(
                self.name, html,
                default_org="UNDP",
                base_url="https://procurement-notices.undp.org",
            )
            for g in grants:
                g.region = g.region or "Global"
                g.category = g.category or "International Development"
                if not g.country:
                    g.country = self._extract_country(g.title)
            logger.info(f"[undp_grants] stealth+adaptive scraped {len(grants)} grants")
            return grants
        finally:
            await parser.close()

    def _extract_country(self, title: str) -> Optional[str]:
        parts = title.split("-")
        if len(parts) >= 2:
            return parts[1].strip()
        return None
