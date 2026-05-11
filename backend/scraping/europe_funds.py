"""
European national funding programs: Innosuisse (Switzerland), Innovation Fund Denmark.
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

# Innovation Fund Denmark has an open JSON calls list
IFD_API = "https://innovationsfonden.dk/en/grants"

# Innosuisse open calls page
INNOSUISSE_URL = "https://www.innosuisse.ch/inno/en/home/funding/innovation-projects.html"


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


def _extract_grant_links(html: str, base_domain: str) -> list[tuple[str, str]]:
    """Extract (title, url) pairs from grant listing HTML."""
    results = []
    # Look for <a href="...">Title</a> patterns in grant listings
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*<[^>]+>\s*([^<]{10,})\s*<',
        html, re.I | re.S
    ):
        href, title = m.group(1).strip(), m.group(2).strip()
        if len(title) > 10 and not href.startswith("mailto"):
            if not href.startswith("http"):
                href = base_domain.rstrip("/") + "/" + href.lstrip("/")
            results.append((title, href))
    return results[:10]


class InnosuisseScraper(BaseScraper):
    name = "innosuisse"

    async def scrape(self) -> list[GrantData]:
        results = []
        urls_to_try = [
            ("https://www.innosuisse.ch/inno/en/home/funding/innovation-projects.html",
             "Innovation Projects"),
            ("https://www.innosuisse.ch/inno/en/home/funding/startup-training.html",
             "Start-up Training"),
            ("https://www.innosuisse.ch/inno/en/home/funding/flagship-initiatives.html",
             "Flagship Initiatives"),
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url, program_name in urls_to_try:
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    desc = _meta_desc(r.text) or (
                        f"Innosuisse {program_name}: Swiss National Innovation Agency funding "
                        "for collaborative R&D projects between companies and research institutions. "
                        "Supports innovation projects, start-up training, and technology transfer."
                    )
                    results.append(GrantData(
                        title=f"Innosuisse — {program_name}",
                        source_url=url,
                        organization="Innosuisse",
                        description=desc,
                        country="Switzerland",
                        category="R&D Grant — Swiss Innovation",
                        deadline=None,
                    ))
                except Exception as e:
                    logger.debug(f"[innosuisse] {url}: {e}")

        if not results:
            # Fallback: return known static entry
            results.append(GrantData(
                title="Innosuisse Innovation Projects",
                source_url="https://www.innosuisse.ch/inno/en/home/funding.html",
                organization="Innosuisse",
                description=(
                    "Innosuisse funds R&D and innovation projects between Swiss companies and "
                    "research institutions. Grants cover up to 100% of research partner costs. "
                    "Rolling submission with regular evaluation rounds."
                ),
                country="Switzerland",
                category="R&D Grant — Swiss Innovation",
                deadline=None,
            ))

        logger.info(f"[innosuisse] Scraped {len(results)} opportunities")
        return results


class InnovationFundDenmarkScraper(BaseScraper):
    name = "innovation_fund_denmark"

    async def scrape(self) -> list[GrantData]:
        urls_to_try = [
            "https://innovationsfonden.dk/en/calls",
            "https://innovationsfonden.dk/en/grants",
            "https://innovationsfonden.dk/en",
        ]
        async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
            for url in urls_to_try:
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    desc = _meta_desc(r.text)

                    # Try to find individual call links
                    links = _extract_grant_links(r.text, "https://innovationsfonden.dk")
                    if links:
                        results = []
                        for title, link_url in links[:5]:
                            if "call" in link_url.lower() or "grant" in link_url.lower() or "fund" in link_url.lower():
                                results.append(GrantData(
                                    title=title[:200],
                                    source_url=link_url,
                                    organization="Innovation Fund Denmark",
                                    description=desc or "Innovation Fund Denmark supports research, innovation, and entrepreneurship in Denmark.",
                                    country="Denmark",
                                    category="R&D Grant — Danish Innovation",
                                    deadline=None,
                                ))
                        if results:
                            logger.info(f"[innovation_fund_denmark] Scraped {len(results)} opportunities")
                            return results

                    # Fallback to a single entry
                    logger.info("[innovation_fund_denmark] Scraped 1 opportunity (static)")
                    return [GrantData(
                        title="Innovation Fund Denmark — Open Calls",
                        source_url=url,
                        organization="Innovation Fund Denmark",
                        description=desc or (
                            "Innovation Fund Denmark invests in research and innovation that benefits "
                            "society and creates growth. Funds range from small seed grants to large "
                            "Grand Solutions projects. Multiple calls per year across all sectors."
                        ),
                        country="Denmark",
                        category="R&D Grant — Danish Innovation",
                        deadline=None,
                    )]
                except Exception as e:
                    logger.debug(f"[innovation_fund_denmark] {url}: {e}")

        logger.warning("[innovation_fund_denmark] All pages unreachable")
        return []
