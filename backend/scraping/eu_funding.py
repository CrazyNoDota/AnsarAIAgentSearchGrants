"""
Scraper for EU Funding & Tenders Portal via RSS feed.
RSS feed provides stable, structured data without HTML parsing.
"""
import logging
from datetime import datetime
from typing import Optional

import feedparser

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

EU_RSS_FEEDS = [
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/feeders/all_open.json",
]

# Alternative: use the public search API
EU_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


class EUFundingScraper(BaseScraper):
    name = "eu_funding"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            import httpx
            # Use EU Funding Tenders Portal open data API
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

            results_raw = data.get("results", [])
            for item in results_raw:
                metadata = item.get("metadata", {})
                title = self._first(metadata.get("title", []))
                url = self._first(metadata.get("callDetailsPage", []))
                deadline_str = self._first(metadata.get("deadlineDate", []))
                org = "European Commission"
                category = self._first(metadata.get("programmeName", []))
                description = self._first(metadata.get("callTitle", []))

                if not title or not url:
                    continue

                grant = GrantData(
                    title=title,
                    source_url=url,
                    organization=org,
                    description=description,
                    country="European Union",
                    category=category,
                    deadline=self._parse_date(deadline_str),
                )
                results.append(grant)

            logger.info(f"[eu_funding] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[eu_funding] Scrape failed: {e}")

        return results

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
