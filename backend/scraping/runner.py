"""
Orchestrates all scrapers and saves results to the database.
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraping.base_scraper import GrantData
from scraping.grants_gov import GrantsGovScraper
from scraping.federal_register import FederalRegisterScraper
from scraping.world_bank import WorldBankScraper
from scraping.nsf import NSFScraper
from scraping.eu_funding import EUFundingScraper
from scraping.undp_grants import UNDPScraper
from scraping.nasa_sbir import NASASBIRScraper
from scraping.innovate_uk import InnovateUKScraper
from scraping.nih_sbir import NIHSBIRScraper
from database.connection import AsyncSessionLocal
from models.grant import Grant

logger = logging.getLogger(__name__)

ALL_SCRAPERS = [
    GrantsGovScraper(),
    FederalRegisterScraper(),
    WorldBankScraper(),
    NSFScraper(),
    EUFundingScraper(),
    UNDPScraper(),
    NASASBIRScraper(),
    InnovateUKScraper(),
    NIHSBIRScraper(),
]


async def bulk_save_grants(db: AsyncSession, grants: list[GrantData]) -> tuple[int, int]:
    """
    Fetch all known URLs in one query, filter dupes in Python, then add only
    new grants via ORM add_all. Two DB round-trips regardless of batch size.
    Returns (new_count, skipped_count).
    """
    if not grants:
        return 0, 0

    candidate_urls = {g.source_url for g in grants}
    existing = await db.execute(
        select(Grant.source_url).where(Grant.source_url.in_(candidate_urls))
    )
    existing_urls = {row[0] for row in existing}

    new_grants = [
        Grant(
            title=g.title,
            description=g.description or "",
            organization=g.organization or "",
            country=g.country or "",
            category=g.category or "",
            deadline=g.deadline,
            source_url=g.source_url,
            status="pending",
            ai_score=0.0,
        )
        for g in grants
        if g.source_url not in existing_urls
    ]

    if new_grants:
        db.add_all(new_grants)
        await db.flush()

    return len(new_grants), len(grants) - len(new_grants)


async def run_all_scrapers_async() -> dict:
    """Run all scrapers concurrently and persist results. Returns summary."""
    import asyncio

    summary: dict = {
        "total": 0, "new": 0, "skipped": 0, "errors": 0,
        "by_source": {}, "last_error": None,
    }

    async def _run_one(scraper):
        try:
            logger.info(f"Running scraper: {scraper.name}")
            return scraper.name, await scraper.scrape(), None
        except Exception as e:
            logger.error(f"Scraper {scraper.name} failed: {e}")
            return scraper.name, [], f"[{scraper.name}] {e.__class__.__name__}: {e}"

    # Fetch all sources concurrently — total time ≈ slowest single scraper.
    scrape_results = await asyncio.gather(
        *(_run_one(s) for s in ALL_SCRAPERS),
        return_exceptions=False,
    )

    async with AsyncSessionLocal() as db:
        for source_name, grants, scrape_err in scrape_results:
            source_summary = {"total": len(grants), "new": 0, "skipped": 0, "errors": 0}

            if scrape_err:
                summary["errors"] += 1
                source_summary["errors"] += 1
                if summary["last_error"] is None:
                    summary["last_error"] = scrape_err

            summary["total"] += len(grants)

            if grants:
                try:
                    new_c, skip_c = await bulk_save_grants(db, grants)
                    await db.commit()
                    summary["new"] += new_c
                    summary["skipped"] += skip_c
                    source_summary["new"] = new_c
                    source_summary["skipped"] = skip_c
                except Exception as e:
                    await db.rollback()
                    logger.error(f"Bulk save failed for {source_name}: {e}")
                    summary["errors"] += 1
                    source_summary["errors"] += len(grants)
                    if summary["last_error"] is None:
                        summary["last_error"] = f"[{source_name}] {e.__class__.__name__}: {e}"

            summary["by_source"][source_name] = source_summary

    logger.info(f"Scraping complete: {summary}")
    return summary
