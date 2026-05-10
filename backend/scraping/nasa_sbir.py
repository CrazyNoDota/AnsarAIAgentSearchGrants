"""
NASA SBIR/STTR open solicitations.
Public API: https://api.sbir.gov/public/api/solicitations
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

API_URL = "https://api.sbir.gov/public/api/solicitations"


class NASASBIRScraper(BaseScraper):
    name = "nasa_sbir"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        params = {
            "agency": "NASA",
            "open": 1,
            "rows": 50,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            for item in data if isinstance(data, list) else data.get("results", []):
                title = (item.get("program") or item.get("title") or "").strip()
                sol_id = item.get("solicitation_id") or item.get("solicitation_number") or ""
                url = item.get("solicitation_url") or f"https://sbir.nasa.gov/solicitations/{sol_id}"

                if not title:
                    continue

                deadline = self._parse_date(
                    item.get("close_date") or item.get("deadline") or ""
                )
                description = (item.get("description") or item.get("abstract") or "").strip()[:1500]
                topic = (item.get("topic_code") or item.get("program_desc") or "").strip()

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="NASA",
                    description=description,
                    country="United States",
                    category=f"SBIR/STTR — {topic}" if topic else "SBIR/STTR",
                    deadline=deadline,
                ))

            logger.info(f"[nasa_sbir] Scraped {len(results)} solicitations")
        except Exception as e:
            logger.error(f"[nasa_sbir] Scrape failed: {e}")

        return results

    def _parse_date(self, s: str) -> Optional[datetime.date]:
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt).date()
            except (ValueError, TypeError):
                continue
        return None
