"""
Fellowship and scholarship programs:
HFSP, Schmidt Science Fellows, Quad Fellowship, Bolashaq.
"""
import re
import logging

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


class HFSPScraper(BaseScraper):
    name = "hfsp_fellowship"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.hfsp.org/funding/hfsp-funding/postdoctoral-fellowships"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[hfsp_fellowship] Page unreachable")
            return []
        description = desc or (
            "HFSP (Human Frontier Science Program) Postdoctoral Fellowships support cutting-edge "
            "interdisciplinary research in life sciences. Long-Term Fellowships for researchers "
            "moving between disciplines; Cross-Disciplinary Fellowships for those coming from "
            "non-biological fields. Annual stipend ~$55,000 USD. Application deadline: August."
        )
        logger.info("[hfsp_fellowship] Scraped 1 opportunity")
        return [GrantData(
            title="HFSP Postdoctoral Fellowship",
            source_url=url,
            organization="Human Frontier Science Program",
            description=description,
            country="Global",
            category="Fellowship — Life Sciences Research",
            deadline=None,
        )]


class SchmidtScienceScraper(BaseScraper):
    name = "schmidt_science_fellows"

    async def scrape(self) -> list[GrantData]:
        url = "https://schmidtsciencefellows.org/apply/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[schmidt_science_fellows] Page unreachable")
            return []
        description = desc or (
            "Schmidt Science Fellows supports postdoctoral scientists to pivot their research "
            "into a new scientific discipline. Fellows receive $100,000/year for up to two years, "
            "plus access to a global network of scientific leaders. "
            "Nominations required through PhD-granting institutions."
        )
        logger.info("[schmidt_science_fellows] Scraped 1 opportunity")
        return [GrantData(
            title="Schmidt Science Fellows",
            source_url=url,
            organization="Schmidt Futures",
            description=description,
            country="Global",
            category="Fellowship — Postdoctoral Science",
            deadline=None,
        )]


class QuadFellowshipScraper(BaseScraper):
    name = "quad_fellowship"

    async def scrape(self) -> list[GrantData]:
        url = "https://quadfellowship.org/apply"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[quad_fellowship] Page unreachable")
            return []
        description = desc or (
            "The Quad Fellowship is a scholarship for STEM graduate students from the United States, "
            "Australia, India, and Japan to study in the US. Provides $50,000 over two years plus "
            "networking, leadership development, and cultural exchange across Quad nations."
        )
        logger.info("[quad_fellowship] Scraped 1 opportunity")
        return [GrantData(
            title="Quad Fellowship",
            source_url=url,
            organization="Quad Fellowship / IIE",
            description=description,
            country="United States",
            category="Fellowship — STEM Graduate Studies",
            deadline=None,
        )]


class BolashaqScraper(BaseScraper):
    name = "bolashaq"

    async def scrape(self) -> list[GrantData]:
        url = "https://bolashaq.kz/en/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[bolashaq] Page unreachable")
            return []
        description = desc or (
            "The Bolashaq International Scholarship Program funds Kazakhstani citizens to study "
            "at top universities abroad (Master's, PhD, internships). Covers tuition, living "
            "expenses, and travel. Annual competition open to students and professionals."
        )
        logger.info("[bolashaq] Scraped 1 opportunity")
        return [GrantData(
            title="Bolashaq International Scholarship",
            source_url=url,
            organization="JSC Center for International Programs (Kazakhstan)",
            description=description,
            country="Kazakhstan",
            category="Scholarship — International Study",
            deadline=None,
        )]
