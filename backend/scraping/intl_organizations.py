"""
International organizations and foundations:
WFP Innovation Accelerator, WHO Innovation, USAID Central Asia,
Gates Foundation, Global Innovation Fund.
"""
import re
import logging
from datetime import datetime
from typing import Optional

import httpx

from scraping.base_scraper import BaseScraper, GrantData

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# USAID Development Experience Clearinghouse API
USAID_DEC_API = "https://dec.usaid.gov/api/fdpselect/?type=project&Operating_Unit_Name=Central+Asia&pageSize=20&pageNum=1"


def _meta_desc(html: str) -> str:
    for pat in [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,})',
        r'<meta[^>]+content=["\']([^"\']{10,})["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{10,})',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    return ""


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code == 200:
            return True, _meta_desc(r.text)
        return False, ""
    except Exception:
        return False, ""


class WFPInnovationScraper(BaseScraper):
    name = "wfp_innovation"

    async def scrape(self) -> list[GrantData]:
        url = "https://innovation.wfp.org/get-funding"
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            live, desc = await _fetch(client, url)
        if not live:
            url = "https://innovation.wfp.org/"
            async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client2:
                live, desc = await _fetch(client2, url)
        description = desc or (
            "The WFP Innovation Accelerator discovers, funds, and scales high-impact innovations "
            "to end hunger. Provides seed funding ($100K–$1M), expert support, and access to "
            "WFP's global operations. Open to startups, NGOs, and social enterprises globally."
        )
        logger.info("[wfp_innovation] Scraped 1 opportunity")
        return [GrantData(
            title="WFP Innovation Accelerator",
            source_url=url,
            organization="UN World Food Programme",
            description=description,
            country="Global",
            category="Innovation Grant — Food Security / UN",
            deadline=None,
        )]


class WHOInnovationScraper(BaseScraper):
    name = "who_innovation"

    async def scrape(self) -> list[GrantData]:
        urls_to_try = [
            "https://www.who.int/about/funding/innovation",
            "https://www.who.int/initiatives/who-innovation",
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url in urls_to_try:
                live, desc = await _fetch(client, url)
                if live:
                    description = desc or (
                        "WHO Innovation Challenge funds solutions to critical global health problems. "
                        "Open to startups, researchers, and NGOs worldwide. Focus areas include "
                        "digital health, diagnostics, vaccines, and health systems strengthening."
                    )
                    logger.info("[who_innovation] Scraped 1 opportunity")
                    return [GrantData(
                        title="WHO Innovation Challenge",
                        source_url=url,
                        organization="World Health Organization",
                        description=description,
                        country="Global",
                        category="Innovation Grant — Global Health / UN",
                        deadline=None,
                    )]
        logger.warning("[who_innovation] All pages unreachable")
        return []


class USAIDCentralAsiaScraper(BaseScraper):
    name = "usaid_central_asia"

    async def scrape(self) -> list[GrantData]:
        results = []

        # Try the USAID DEC API for Central Asia projects
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=25) as client:
                r = await client.get(USAID_DEC_API)
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data", data if isinstance(data, list) else [])
                    for item in items[:10]:
                        title = (
                            item.get("Project_Title") or
                            item.get("Title") or
                            item.get("title") or ""
                        ).strip()
                        if not title:
                            continue
                        url = (
                            item.get("URL") or
                            item.get("url") or
                            "https://www.usaid.gov/central-asia"
                        )
                        results.append(GrantData(
                            title=title,
                            source_url=url,
                            organization="USAID",
                            description=(item.get("Description") or item.get("description") or "").strip()[:1500],
                            country="Central Asia",
                            category="USAID Development Grant — Central Asia",
                            deadline=None,
                        ))
        except Exception as e:
            logger.debug(f"[usaid_central_asia] DEC API failed: {e}")

        # Fallback to HTML page
        if not results:
            url = "https://www.usaid.gov/central-asia/business-opportunities"
            async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
                live, desc = await _fetch(client, url)
            if not live:
                url = "https://www.usaid.gov/central-asia"
                async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client2:
                    live, desc = await _fetch(client2, url)
            description = desc or (
                "USAID Central Asia programs support entrepreneurs, NGOs, and local organizations "
                "across Kazakhstan, Kyrgyzstan, Tajikistan, Turkmenistan, and Uzbekistan. "
                "Grants and cooperative agreements for innovation, democracy, and economic growth."
            )
            results.append(GrantData(
                title="USAID Central Asia Innovators Program",
                source_url=url,
                organization="USAID",
                description=description,
                country="Central Asia",
                category="USAID Development Grant — Central Asia",
                deadline=None,
            ))

        logger.info(f"[usaid_central_asia] Scraped {len(results)} opportunities")
        return results


class GatesFoundationScraper(BaseScraper):
    name = "gates_foundation"

    async def scrape(self) -> list[GrantData]:
        urls_to_try = [
            "https://www.gatesfoundation.org/about/committed-grants",
            "https://gcgh.grandchallenges.org/challenges",
            "https://gcgh.grandchallenges.org/",
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url in urls_to_try:
                live, desc = await _fetch(client, url)
                if live:
                    description = desc or (
                        "The Bill & Melinda Gates Foundation Grand Challenges program funds "
                        "bold and innovative solutions in global health, development, and education. "
                        "Open rounds with grants from $100K to several million USD. "
                        "Focus on underserved populations in low- and middle-income countries."
                    )
                    logger.info("[gates_foundation] Scraped 1 opportunity")
                    return [GrantData(
                        title="Gates Foundation Grand Challenges",
                        source_url=url,
                        organization="Bill & Melinda Gates Foundation",
                        description=description,
                        country="Global",
                        category="Innovation Grant — Global Health & Development",
                        deadline=None,
                    )]

        logger.warning("[gates_foundation] All pages unreachable")
        return []


class GlobalInnovationFundScraper(BaseScraper):
    name = "global_innovation_fund"

    async def scrape(self) -> list[GrantData]:
        urls_to_try = [
            "https://www.globalinnovation.fund/apply/",
            "https://www.globalinnovation.fund/",
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url in urls_to_try:
                live, desc = await _fetch(client, url)
                if live:
                    description = desc or (
                        "The Global Innovation Fund (GIF) invests in innovations that help "
                        "the poorest people in developing countries. Provides grants and "
                        "investments from $50K (pilot) to $15M (scale). Open to NGOs, social "
                        "enterprises, and for-profit companies. Rolling applications."
                    )
                    logger.info("[global_innovation_fund] Scraped 1 opportunity")
                    return [GrantData(
                        title="Global Innovation Fund",
                        source_url=url,
                        organization="Global Innovation Fund",
                        description=description,
                        country="Global",
                        category="Innovation Grant — Global Development",
                        deadline=None,
                    )]

        logger.warning("[global_innovation_fund] All pages unreachable")
        return []
