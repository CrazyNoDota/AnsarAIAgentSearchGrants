"""
Scraper for grants.gov (USA federal grants).
Uses the public grants.gov REST API — no scraping needed, stable JSON.
API docs: https://www.grants.gov/web/grants/search-grants.html
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

GRANTS_GOV_API = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"


class GrantsGovScraper(BaseScraper):
    name = "grants.gov"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        payload = {
            "keyword": "",
            "oppNum": "",
            "cfda": "",
            "oppStatuses": "forecasted|posted",
            "rows": 50,
            "startRecordNum": 0,
            "sortBy": "openDate|desc",
            "eligibilities": "",
            "agencyCode": "",
            "fundingCategories": "",
            "fundingInstruments": "",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(GRANTS_GOV_API, json=payload)
                resp.raise_for_status()
                data = resp.json()

            opportunities = data.get("oppHits", [])
            for opp in opportunities:
                deadline = self._parse_date(opp.get("closeDate", ""))
                grant = GrantData(
                    title=opp.get("title", "Untitled Grant"),
                    source_url=f"https://www.grants.gov/search-results-detail/{opp.get('id', '')}",
                    organization=opp.get("agencyName") or opp.get("agencyCode") or "US Federal Government",
                    description=opp.get("synopsis", ""),
                    country="United States",
                    category=opp.get("fundingCategory", ""),
                    deadline=deadline,
                )
                results.append(grant)

            logger.info(f"[grants.gov] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[grants.gov] Scrape failed: {e}")

        return results

    def _parse_date(self, date_str: str) -> Optional[datetime.date]:
        if not date_str:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
