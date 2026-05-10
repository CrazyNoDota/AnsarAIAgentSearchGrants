"""
World Bank Projects API — global development projects, all sectors.
Public JSON at https://search.worldbank.org/api/v3/projects (no auth).
Returns approved/active projects across ~190 countries.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

API_URL = "https://search.worldbank.org/api/v3/projects"


class WorldBankScraper(BaseScraper):
    name = "world_bank"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        params = {
            "format": "json",
            "rows": 50,
            "os": 0,
            "fl": (
                "id,project_name,countryshortname,boardapprovaldate,"
                "closingdate,sector1,project_abstract,url,status"
            ),
            "frmYear": datetime.utcnow().year - 1,
            "srt": "boardapprovaldate",
            "order": "desc",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            projects = data.get("projects") or {}
            for pid, p in projects.items():
                title = (p.get("project_name") or "").strip()
                if not title:
                    continue

                # Project URL — World Bank's API field is sometimes empty, so
                # construct the canonical detail URL from the project ID.
                url = (p.get("url") or "").strip()
                if not url:
                    url = f"https://projects.worldbank.org/en/projects-operations/project-detail/{pid}"

                country = (p.get("countryshortname") or "").strip() or None
                sector = ""
                s1 = p.get("sector1")
                if isinstance(s1, dict):
                    sector = (s1.get("Name") or "").strip()
                elif isinstance(s1, str):
                    sector = s1

                # closingdate is the end of project funding, not an application deadline
                deadline = self._parse_date(p.get("closingdate"))

                abstract = ""
                ab = p.get("project_abstract")
                if isinstance(ab, dict):
                    abstract = (ab.get("cdata") or "").strip()
                elif isinstance(ab, str):
                    abstract = ab.strip()

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="World Bank",
                    description=abstract[:1500],
                    country=country,
                    category=sector or "International Development",
                    deadline=deadline,
                ))

            logger.info(f"[world_bank] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[world_bank] Scrape failed: {e}")

        return results

    def _parse_date(self, value) -> Optional[datetime.date]:
        if not value:
            return None
        # World Bank returns ISO strings or epoch milliseconds depending on field
        if isinstance(value, (int, float)):
            try:
                return datetime.utcfromtimestamp(value / 1000).date()
            except (ValueError, OSError):
                return None
        s = str(value)[:10]
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
