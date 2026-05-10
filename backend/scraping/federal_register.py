"""
US Federal Register — grant notices across every federal agency.
Public JSON API at https://www.federalregister.gov/developers/documentation/api/v1
No auth required, returns ~10k matching docs for a "notice of funding" query.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

API_URL = "https://www.federalregister.gov/api/v1/documents.json"

# Title-level filter — the API search is broad, so we only keep documents whose
# title indicates an actual funding opportunity rather than a notice/comment.
_FUNDING_KEYWORDS = (
    "funding opportunity",
    "notice of funding",
    "request for applications",
    "request for proposals",
    "competitive grant",
    "grant program",
    "grants program",
    "grant announcement",
    "grant solicitation",
)


class FederalRegisterScraper(BaseScraper):
    name = "federal_register"

    async def scrape(self) -> list[GrantData]:
        results: list[GrantData] = []
        params = {
            "per_page": 50,
            "conditions[term]": "notice of funding opportunity",
            "conditions[type][]": "NOTICE",
            "order": "newest",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            for doc in data.get("results", []):
                title = (doc.get("title") or "").strip()
                if not title:
                    continue
                title_lower = title.lower()
                if not any(kw in title_lower for kw in _FUNDING_KEYWORDS):
                    continue  # noise: stakeholder meetings, OMB reviews, etc.

                url = doc.get("html_url") or ""
                if not url:
                    continue

                agencies = doc.get("agencies") or []
                org = (agencies[0].get("name") if agencies else None) or "US Federal Government"

                # Federal Register publication date is approximate — the actual
                # application deadline lives in the document body and isn't
                # exposed via this endpoint.
                pub_date_str = doc.get("publication_date") or ""
                pub_date = None
                try:
                    if pub_date_str:
                        pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d").date()
                except ValueError:
                    pub_date = None

                description = (doc.get("abstract") or "")[:1000]

                results.append(GrantData(
                    title=title,
                    source_url=url,
                    organization=org,
                    description=description,
                    country="United States",
                    category="Federal Grant Notice",
                    deadline=None,  # not in API response — open the URL to see
                ))

            logger.info(f"[federal_register] Scraped {len(results)} grants")
        except Exception as e:
            logger.error(f"[federal_register] Scrape failed: {e}")

        return results
