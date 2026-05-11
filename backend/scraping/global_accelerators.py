"""
Global accelerator and startup programs:
Antler, Techstars, IFundWomen, German Accelerator, GIST, Misk, KAUST.
"""
import re
import logging
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


class AntlerScraper(BaseScraper):
    name = "antler"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.antler.co/apply"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[antler] Page unreachable")
            return []
        description = desc or (
            "Antler is a global early-stage venture capital firm that invests in exceptional "
            "founders. Provides pre-seed funding (equity investment), a 10-week program, "
            "global network, and ongoing support. Runs cohorts across 30+ countries."
        )
        logger.info("[antler] Scraped 1 opportunity")
        return [GrantData(
            title="Antler Global Residency Program",
            source_url=url,
            organization="Antler",
            description=description,
            country="Global",
            category="Accelerator — Pre-Seed Investment",
            deadline=None,
        )]


class TechstarsGrantsScraper(BaseScraper):
    name = "techstars_grants"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.techstars.com/the-line/announcements/techstars-equity-free-grants"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            url = "https://www.techstars.com/programs"
            async with httpx.AsyncClient(headers=HEADERS) as client2:
                live, desc = await _fetch(client2, url)
        if not live:
            logger.warning("[techstars_grants] Page unreachable")
            return []
        description = desc or (
            "Techstars offers equity-free grants and accelerator programs for early-stage "
            "startups. The Techstars Accelerator provides $120K in funding ($20K equity-free) "
            "plus access to the global Techstars network of mentors and investors."
        )
        logger.info("[techstars_grants] Scraped 1 opportunity")
        return [GrantData(
            title="Techstars Accelerator & Grants",
            source_url="https://www.techstars.com/programs",
            organization="Techstars",
            description=description,
            country="Global",
            category="Accelerator — Startup Funding",
            deadline=None,
        )]


class IFundWomenScraper(BaseScraper):
    name = "ifundwomen"

    async def scrape(self) -> list[GrantData]:
        url = "https://ifundwomen.com/grants"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[ifundwomen] Page unreachable")
            return []
        description = desc or (
            "IFundWomen connects women-owned businesses with grants, coaching, and community. "
            "Offers rolling grant applications up to $25,000 for women entrepreneurs. "
            "Partners with major brands to fund women-owned small businesses."
        )
        logger.info("[ifundwomen] Scraped 1 opportunity")
        return [GrantData(
            title="IFundWomen Grant Program",
            source_url=url,
            organization="IFundWomen",
            description=description,
            country="United States",
            category="Grant — Women Entrepreneurs",
            deadline=None,
        )]


class GermanAcceleratorScraper(BaseScraper):
    name = "german_accelerator"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.germanaccelerator.com/programs/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[german_accelerator] Page unreachable")
            return []
        description = desc or (
            "The German Accelerator helps high-potential German startups scale globally "
            "in the US, Southeast Asia, and India. Offers an intensive program with mentoring, "
            "office space, and a global network. Equity-free, government-supported."
        )
        logger.info("[german_accelerator] Scraped 1 opportunity")
        return [GrantData(
            title="German Accelerator Scale Program",
            source_url=url,
            organization="German Accelerator",
            description=description,
            country="Germany",
            category="Accelerator — International Scale-Up",
            deadline=None,
        )]


class GISTNetworkScraper(BaseScraper):
    name = "gist_network"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.gistnetwork.org/get-involved"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[gist_network] Page unreachable")
            return []
        description = desc or (
            "GIST (Global Innovation through Science and Technology) supports science-based "
            "entrepreneurs in emerging markets through training, mentorship, and funding "
            "competitions. Programs available across Africa, Asia, Latin America, and MENA."
        )
        logger.info("[gist_network] Scraped 1 opportunity")
        return [GrantData(
            title="GIST Startup Bootcamp & Competitions",
            source_url=url,
            organization="GIST Network / USAID",
            description=description,
            country="Global",
            category="Accelerator — Science & Technology Startups",
            deadline=None,
        )]


class MiskAcceleratorScraper(BaseScraper):
    name = "misk_accelerator"

    async def scrape(self) -> list[GrantData]:
        url = "https://misk.org.sa/en/programs/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[misk_accelerator] Page unreachable")
            return []
        description = desc or (
            "Misk Foundation (500 Global partnership) runs accelerator programs for Saudi and "
            "MENA entrepreneurs. Provides funding, mentorship, and connections to global "
            "investors. Focus on tech-enabled startups with growth potential."
        )
        logger.info("[misk_accelerator] Scraped 1 opportunity")
        return [GrantData(
            title="Misk Accelerator (500 Global)",
            source_url=url,
            organization="Misk Foundation",
            description=description,
            country="Saudi Arabia",
            category="Accelerator — MENA Tech Startups",
            deadline=None,
        )]


class KAUSTScraper(BaseScraper):
    name = "kaust_entrepreneurship"

    async def scrape(self) -> list[GrantData]:
        url = "https://entrepreneurship.kaust.edu.sa/funding"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            url = "https://entrepreneurship.kaust.edu.sa/"
            async with httpx.AsyncClient(headers=HEADERS) as client2:
                live, desc = await _fetch(client2, url)
        if not live:
            logger.warning("[kaust_entrepreneurship] Page unreachable")
            return []
        description = desc or (
            "KAUST (King Abdullah University of Science and Technology) offers deep tech "
            "entrepreneurship programs including TAQADAM startup accelerator and proof-of-concept "
            "grants up to SAR 400,000 (~$100K). Focus on hard-tech, biotech, and AI."
        )
        logger.info("[kaust_entrepreneurship] Scraped 1 opportunity")
        return [GrantData(
            title="KAUST Entrepreneurship Fund & TAQADAM",
            source_url=url,
            organization="KAUST",
            description=description,
            country="Saudi Arabia",
            category="Accelerator — Deep Tech / Hard Tech",
            deadline=None,
        )]
