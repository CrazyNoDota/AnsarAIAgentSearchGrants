"""
Scraper for UNDP procurement notices.
Uses UNDP's public procurement RSS feed.
"""
import logging
from datetime import datetime
from typing import Optional

import feedparser

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

UNDP_RSS = "https://procurement-notices.undp.org/index.cfm?view=RSS"


class UNDPScraper(BaseScraper):
    name = "undp_grants"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            import asyncio
            # feedparser is sync — run in executor
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, UNDP_RSS)

            for entry in feed.entries[:25]:
                title = entry.get("title", "")
                url = entry.get("link", "")
                description = entry.get("summary", "")
                published = entry.get("published", "")

                if not title or not url:
                    continue

                grant = GrantData(
                    title=title,
                    source_url=url,
                    organization="UNDP",
                    description=description,
                    country=self._extract_country(title),
                    category="International Development",
                    deadline=None,  # UNDP RSS doesn't always include deadline
                )
                results.append(grant)

            logger.info(f"[undp_grants] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[undp_grants] Scrape failed: {e}")

        return results

    def _extract_country(self, title: str) -> Optional[str]:
        """Try to extract country from title like 'RFP - Country - Project Name'."""
        parts = title.split("-")
        if len(parts) >= 2:
            return parts[1].strip()
        return None
