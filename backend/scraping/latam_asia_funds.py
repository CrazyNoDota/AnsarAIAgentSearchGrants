"""
Regional funding programs: Latin America, Asia, Central Asia.
Start-Up Chile, FAPESP, Hong Kong ITF, KOSGEB, TÜBİTAK, Astana Hub, Bolashaq (see fellowships.py).
"""
import re
import json
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


class StartupChileScraper(BaseScraper):
    name = "startup_chile"

    async def scrape(self) -> list[GrantData]:
        results = []
        programs = [
            ("S Factory", "https://www.startupchile.org/programs/s-factory/",
             "Pre-acceleration for women-led startups. Equity-free grant ~USD 20,000."),
            ("Build", "https://www.startupchile.org/programs/build/",
             "Early-stage startups with MVP. Equity-free grant ~USD 40,000."),
            ("Scale", "https://www.startupchile.org/programs/scale/",
             "Growth-stage startups with traction. Equity-free grant ~USD 100,000."),
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for program_name, url, fallback_desc in programs:
                live, desc = await _fetch(client, url)
                if live:
                    results.append(GrantData(
                        title=f"Start-Up Chile — {program_name}",
                        source_url=url,
                        organization="Start-Up Chile (CORFO)",
                        description=desc or fallback_desc,
                        country="Chile",
                        category="Accelerator Grant — Chilean Government",
                        deadline=None,
                    ))
        if not results:
            results.append(GrantData(
                title="Start-Up Chile Grant Programs",
                source_url="https://www.startupchile.org/programs/",
                organization="Start-Up Chile (CORFO)",
                description=(
                    "Start-Up Chile is a government-funded startup accelerator that provides "
                    "equity-free grants ($20K–$100K USD) to early and growth-stage startups "
                    "from anywhere in the world. Programs: S Factory, Build, and Scale."
                ),
                country="Chile",
                category="Accelerator Grant — Chilean Government",
                deadline=None,
            ))
        logger.info(f"[startup_chile] Scraped {len(results)} opportunities")
        return results


class FAPESPScraper(BaseScraper):
    name = "fapesp_pipe"

    async def scrape(self) -> list[GrantData]:
        url = "https://fapesp.br/pipe"
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[fapesp_pipe] Page unreachable")
            return []
        description = desc or (
            "FAPESP PIPE (Innovative Research in Small Businesses) funds innovative technology "
            "companies in São Paulo, Brazil. Phase 1: up to BRL 200K for proof-of-concept (1 year). "
            "Phase 2: up to BRL 1M for product development (2 years). Rolling submissions."
        )
        logger.info("[fapesp_pipe] Scraped 1 opportunity")
        return [GrantData(
            title="FAPESP PIPE — Innovative Research in Small Businesses",
            source_url=url,
            organization="FAPESP",
            description=description,
            country="Brazil",
            category="R&D Grant — Brazilian Innovation",
            deadline=None,
        )]


class HongKongITFScraper(BaseScraper):
    name = "hongkong_itf"

    async def scrape(self) -> list[GrantData]:
        results = []
        programs = [
            ("Enterprise Support Scheme",
             "https://www.itf.gov.hk/en/funding-programmes/enterprise-support-scheme/index.html",
             "Up to HKD 10M for private companies to conduct R&D projects in Hong Kong."),
            ("Guangdong-Hong Kong Technology Cooperation Funding Scheme",
             "https://www.itf.gov.hk/en/funding-programmes/guangdong-hong-kong-technology-cooperation-funding-scheme/index.html",
             "Supports cross-boundary R&D cooperation between Guangdong and Hong Kong."),
            ("Platform and Application Projects",
             "https://www.itf.gov.hk/en/funding-programmes/platform-and-application-projects/index.html",
             "Large-scale platform projects and applied R&D for key industries."),
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for program_name, url, fallback_desc in programs:
                live, desc = await _fetch(client, url)
                if live:
                    results.append(GrantData(
                        title=f"Hong Kong ITF — {program_name}",
                        source_url=url,
                        organization="Hong Kong Innovation and Technology Fund",
                        description=desc or fallback_desc,
                        country="Hong Kong",
                        category="R&D Grant — Hong Kong Innovation",
                        deadline=None,
                    ))
        if not results:
            results.append(GrantData(
                title="Hong Kong Innovation and Technology Fund (ITF)",
                source_url="https://www.itf.gov.hk/en/funding-programmes/index.html",
                organization="Hong Kong Innovation and Technology Fund",
                description=(
                    "The ITF provides funding to companies and research institutions in Hong Kong "
                    "for R&D and technology adoption. Multiple schemes including the Enterprise "
                    "Support Scheme (up to HKD 10M) and the Technology Voucher Programme."
                ),
                country="Hong Kong",
                category="R&D Grant — Hong Kong Innovation",
                deadline=None,
            ))
        logger.info(f"[hongkong_itf] Scraped {len(results)} opportunities")
        return results


class KOSGEBScraper(BaseScraper):
    name = "kosgeb"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.kosgeb.gov.tr/site/tr/genel/destekler/3/destekler"
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            live, desc = await _fetch(client, url)
        if not live:
            url = "https://www.kosgeb.gov.tr/site/en/genel/anasayfa/1/home"
            async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client2:
                live, desc = await _fetch(client2, url)
        description = desc or (
            "KOSGEB (Small and Medium Enterprises Development Organization of Turkey) supports "
            "Turkish SMEs with grants and soft loans. Programs include R&D support, "
            "entrepreneurship grants (up to TRY 300K), and internationalization support."
        )
        logger.info("[kosgeb] Scraped 1 opportunity")
        return [GrantData(
            title="KOSGEB SME Support Programs",
            source_url="https://www.kosgeb.gov.tr/site/en/genel/anasayfa/1/home",
            organization="KOSGEB",
            description=description,
            country="Turkey",
            category="SME Grant — Turkish Government",
            deadline=None,
        )]


class TUBITAKScraper(BaseScraper):
    name = "tubitak_1512"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.tubitak.gov.tr/en/funds/industry/national-support-programmes/content-1512-techno-enterprise-support-program"
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            live, desc = await _fetch(client, url)
        if not live:
            url = "https://www.tubitak.gov.tr/en/funds/industry/national-support-programmes"
            async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client2:
                live, desc = await _fetch(client2, url)
        description = desc or (
            "TÜBİTAK 1512 Techno-Enterprise Support Program provides seed funding for technology-based "
            "entrepreneurs in Turkey. Phase 1: TRY 150K feasibility grant. Phase 2: up to TRY 1.5M "
            "product development. Phase 3: commercialization support up to TRY 1M."
        )
        logger.info("[tubitak_1512] Scraped 1 opportunity")
        return [GrantData(
            title="TÜBİTAK 1512 Techno-Enterprise Support Program",
            source_url=url,
            organization="TÜBİTAK",
            description=description,
            country="Turkey",
            category="R&D Grant — Turkish Innovation",
            deadline=None,
        )]


class AstanaHubScraper(BaseScraper):
    name = "astana_hub"

    async def scrape(self) -> list[GrantData]:
        urls_to_try = [
            "https://astanahub.com/en/programs/",
            "https://astanahub.com/en/",
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url in urls_to_try:
                live, desc = await _fetch(client, url)
                if live:
                    description = desc or (
                        "Astana Hub is Kazakhstan's international technopark and startup hub. "
                        "Offers seed grants up to USD 25,000, acceleration programs, co-working space, "
                        "and access to Central Asian markets. Focus on IT and tech startups."
                    )
                    logger.info("[astana_hub] Scraped 1 opportunity")
                    return [GrantData(
                        title="Astana Hub Seed Grant & Acceleration",
                        source_url=url,
                        organization="Astana Hub",
                        description=description,
                        country="Kazakhstan",
                        category="Accelerator Grant — Central Asia Tech",
                        deadline=None,
                    )]
        logger.warning("[astana_hub] Page unreachable")
        return []
