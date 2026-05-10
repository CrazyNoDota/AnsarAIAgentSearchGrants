"""
NIH SBIR/STTR funding opportunities.
Uses the NIH Research Portfolio Online Reporting Tools (RePORTER) API.
Also pulls from the NIH SBIR seed fund open topics API.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

# NIH SBIR/STTR open solicitations via seedfund.nsf.gov (covers both NSF + NIH SBIR)
SBIR_API = "https://api.sbir.gov/public/api/solicitations"

# NIH RePORTER API for active funding opportunities
NIH_GRANTS_URL = "https://api.reporter.nih.gov/v2/opportunities/search"


class NIHSBIRScraper(BaseScraper):
    name = "nih_sbir"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []

        # Pull NIH SBIR/STTR open solicitations
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    SBIR_API,
                    params={"agency": "NIH", "open": 1, "rows": 40},
                )
                resp.raise_for_status()
                data = resp.json()

            items = data if isinstance(data, list) else data.get("results", [])
            for item in items:
                title = (item.get("program") or item.get("title") or "").strip()
                sol_id = item.get("solicitation_id") or ""
                url = item.get("solicitation_url") or f"https://grants.nih.gov/grants/guide/notice-files/{sol_id}.html"
                if not title:
                    continue

                deadline = self._parse_date(item.get("close_date") or "")
                description = (item.get("description") or "").strip()[:1500]
                topic = (item.get("program_desc") or item.get("topic_code") or "").strip()

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization="NIH",
                    description=description,
                    country="United States",
                    category=f"NIH SBIR/STTR — {topic}" if topic else "NIH SBIR/STTR",
                    deadline=deadline,
                ))

        except Exception as e:
            logger.warning(f"[nih_sbir] SBIR API failed: {e}, trying NIH Reporter")

        # Supplement with NIH Reporter open funding opportunities
        if len(results) < 5:
            try:
                payload = {
                    "criteria": {"opportunity_status": ["open"]},
                    "offset": 0,
                    "limit": 30,
                    "sort_field": "opportunity_title",
                }
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(NIH_GRANTS_URL, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                for opp in data.get("results", []):
                    title = (opp.get("opportunity_title") or "").strip()
                    url = f"https://grants.nih.gov/grants/guide/notice-files/{opp.get('notice_number', '')}.html"
                    if not title:
                        continue

                    deadline = self._parse_date(opp.get("expiration_date") or "")
                    activity = (opp.get("activity_code") or "").strip()
                    description = (opp.get("opportunity_description") or "").strip()[:1500]

                    results.append(GrantData(
                        title=title,
                        source_url=url,
                        organization="NIH",
                        description=description,
                        country="United States",
                        category=f"NIH {activity}" if activity else "NIH Research Grant",
                        deadline=deadline,
                    ))

            except Exception as e:
                logger.error(f"[nih_sbir] NIH Reporter also failed: {e}")

        logger.info(f"[nih_sbir] Scraped {len(results)} opportunities")
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
