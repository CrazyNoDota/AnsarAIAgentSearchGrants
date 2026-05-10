"""
US National Science Foundation Awards API — science research grants.
Public JSON at https://api.nsf.gov/services/v1/awards.json (no auth).
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

API_URL = "https://api.nsf.gov/services/v1/awards.json"


class NSFScraper(BaseScraper):
    name = "nsf"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        params = {
            "rpp": 50,
            "printFields": (
                "id,title,abstractText,date,fundProgramName,"
                "awardeeName,fundsObligatedAmt"
            ),
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            for award in data.get("response", {}).get("award", []):
                title = (award.get("title") or "").strip()
                award_id = (award.get("id") or "").strip()
                if not title or not award_id:
                    continue

                url = f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}"

                program = (award.get("fundProgramName") or "").strip()
                awardee = (award.get("awardeeName") or "").strip()
                description = (award.get("abstractText") or "").strip()[:1500]

                deadline = None
                date_str = award.get("date") or ""
                # NSF's `date` is the announcement date, not a deadline — leave
                # deadline null and surface it in the description if needed.

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization=f"NSF ({awardee})" if awardee else "National Science Foundation",
                    description=description,
                    country="United States",
                    category=program or "Science Research",
                    deadline=deadline,
                ))

            logger.info(f"[nsf] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[nsf] Scrape failed: {e}")

        return results
