"""
Innovate UK / UKRI open funding opportunities.
Uses UKRI's public opportunities API — no auth required.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

API_URL = "https://apply-for-innovation-funding.service.gov.uk/competition/search"
# UKRI also exposes a JSON feed for active competitions:
UKRI_API = "https://www.ukri.org/wp-json/ukri/v1/funding-finder"


class InnovateUKScraper(BaseScraper):
    name = "innovate_uk"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(
                    UKRI_API,
                    params={"funding_type": "grant", "status": "open", "per_page": 40},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                data = resp.json()

            items = data if isinstance(data, list) else (
                data.get("items") or data.get("results") or data.get("data") or []
            )

            for item in items:
                title = (item.get("title") or item.get("name") or "").strip()
                url = (item.get("link") or item.get("url") or item.get("permalink") or "").strip()
                if not title or not url:
                    continue

                deadline = self._parse_date(
                    item.get("closing_date") or item.get("deadline") or item.get("end_date") or ""
                )
                description = (item.get("summary") or item.get("description") or "").strip()[:1500]
                category = (item.get("funding_type") or item.get("type") or "R&D Grant").strip()
                amount = item.get("amount") or item.get("value") or ""
                if amount:
                    description = f"Funding: {amount}\n\n{description}" if description else f"Funding: {amount}"

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="Innovate UK / UKRI",
                    description=description,
                    country="United Kingdom",
                    category=category,
                    deadline=deadline,
                ))

            logger.info(f"[innovate_uk] Scraped {len(results)} opportunities")
        except Exception as e:
            logger.warning(f"[innovate_uk] UKRI API failed ({e}), trying fallback feed")
            results = await self._scrape_fallback()

        return results

    async def _scrape_fallback(self) -> list[GrantData]:
        """Fallback: parse the Innovate UK Atom/RSS competition feed."""
        import asyncio
        import feedparser

        feed_url = "https://apply-for-innovation-funding.service.gov.uk/competition/search.atom"
        try:
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
            results = []
            for entry in feed.entries[:30]:
                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                if not title or not url:
                    continue
                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="Innovate UK / UKRI",
                    description=(entry.get("summary") or "").strip()[:1500],
                    country="United Kingdom",
                    category="R&D Grant",
                    deadline=None,
                ))
            logger.info(f"[innovate_uk] Fallback scraped {len(results)} entries")
            return results
        except Exception as e:
            logger.error(f"[innovate_uk] Fallback also failed: {e}")
            return []

    def _parse_date(self, s: str) -> Optional[datetime.date]:
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt).date()
            except (ValueError, TypeError):
                continue
        return None
