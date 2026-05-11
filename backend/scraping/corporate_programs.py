"""
Corporate startup/grant programs: AWS, Google, Microsoft, NVIDIA.
These are rolling admission programs — scraper verifies liveness and returns
program info extracted from page meta tags.
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
    """Return (is_live, description)."""
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code == 200:
            return True, _meta_desc(r.text)
        return False, ""
    except Exception:
        return False, ""


class AWSImagineGrantScraper(BaseScraper):
    name = "aws_imagine_grant"

    async def scrape(self) -> list[GrantData]:
        url = "https://aws.amazon.com/government-education/nonprofits/aws-imagine-grant/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[aws_imagine_grant] Page unreachable")
            return []
        description = desc or (
            "The AWS Imagine Grant supports nonprofits using AWS cloud technology "
            "to achieve their mission. Provides up to $100,000 in AWS credits plus "
            "cash grants. Categories include 'Go Further Faster' and 'Momentum to Modernize'."
        )
        logger.info("[aws_imagine_grant] Scraped 1 opportunity")
        return [GrantData(
            title="AWS Imagine Grant",
            source_url=url,
            organization="Amazon Web Services",
            description=description,
            country="United States",
            category="Corporate Grant — Cloud / Nonprofit Tech",
            deadline=None,
        )]


class GoogleForStartupsScraper(BaseScraper):
    name = "google_for_startups"

    async def scrape(self) -> list[GrantData]:
        url = "https://startup.google.com/programs/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[google_for_startups] Page unreachable")
            return []
        description = desc or (
            "Google for Startups offers equity-free support: up to $200K in Google Cloud "
            "credits, technical training, and access to Google's network. Programs include "
            "the Accelerator and the Cloud Program for early-stage startups."
        )
        logger.info("[google_for_startups] Scraped 1 opportunity")
        return [GrantData(
            title="Google for Startups Cloud Program",
            source_url=url,
            organization="Google",
            description=description,
            country="Global",
            category="Corporate Program — Cloud Credits / Accelerator",
            deadline=None,
        )]


class MicrosoftForStartupsScraper(BaseScraper):
    name = "microsoft_for_startups"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.microsoft.com/en-us/startups"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[microsoft_for_startups] Page unreachable")
            return []
        description = desc or (
            "Microsoft for Startups Founders Hub provides up to $150,000 in Azure credits, "
            "access to GitHub, Microsoft 365, LinkedIn, and mentorship from Microsoft experts. "
            "Open to early-stage startups at any stage."
        )
        logger.info("[microsoft_for_startups] Scraped 1 opportunity")
        return [GrantData(
            title="Microsoft for Startups Founders Hub",
            source_url=url,
            organization="Microsoft",
            description=description,
            country="Global",
            category="Corporate Program — Cloud Credits / Tools",
            deadline=None,
        )]


class NVIDIAInceptionScraper(BaseScraper):
    name = "nvidia_inception"

    async def scrape(self) -> list[GrantData]:
        url = "https://www.nvidia.com/en-us/startups/"
        async with httpx.AsyncClient(headers=HEADERS) as client:
            live, desc = await _fetch(client, url)
        if not live:
            logger.warning("[nvidia_inception] Page unreachable")
            return []
        description = desc or (
            "NVIDIA Inception is a free program that helps AI, data science, and HPC startups "
            "with preferred pricing on NVIDIA hardware, marketing support, co-marketing "
            "opportunities, and access to NVIDIA technical experts and investors."
        )
        logger.info("[nvidia_inception] Scraped 1 opportunity")
        return [GrantData(
            title="NVIDIA Inception Program",
            source_url=url,
            organization="NVIDIA",
            description=description,
            country="Global",
            category="Corporate Program — AI / Deep Learning",
            deadline=None,
        )]
