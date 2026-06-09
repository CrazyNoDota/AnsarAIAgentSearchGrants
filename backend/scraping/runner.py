"""
Scraper Orchestrator

Runs all 37 static scrapers + AI Search Agent (Tavily + Firecrawl).
Called by:
  - n8n daily workflow (POST /scraper/run)
  - Manual trigger via API
"""
import asyncio
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
from scraping.gcf_grants import GCFScraper
from scraping.nasa_sbir import NASASBIRScraper
from scraping.innovate_uk import InnovateUKScraper
from scraping.nih_sbir import NIHSBIRScraper
from scraping.corporate_programs import (
    AWSImagineGrantScraper, GoogleForStartupsScraper,
    MicrosoftForStartupsScraper, NVIDIAInceptionScraper,
)
from scraping.global_accelerators import (
    AntlerScraper, TechstarsGrantsScraper, IFundWomenScraper,
    GermanAcceleratorScraper, GISTNetworkScraper,
    MiskAcceleratorScraper, KAUSTScraper,
)
from scraping.fellowships import (
    HFSPScraper, SchmidtScienceScraper, QuadFellowshipScraper, BolashaqScraper,
)
from scraping.europe_funds import InnosuisseScraper, InnovationFundDenmarkScraper
from scraping.latam_asia_funds import (
    StartupChileScraper, FAPESPScraper, HongKongITFScraper,
    KOSGEBScraper, TUBITAKScraper, AstanaHubScraper,
)
from scraping.intl_organizations import (
    WFPInnovationScraper, WHOInnovationScraper, USAIDCentralAsiaScraper,
    GatesFoundationScraper, GlobalInnovationFundScraper,
)
from database.connection import AsyncSessionLocal
from models.grant import Grant
from scraping.budget_parser import parse_budget

logger = logging.getLogger(__name__)

# Sources that fetch through the stealth browser / adaptive LLM parser. These are
# heavy (one camoufox/Firefox session each, 0.5-1.5 GB) so they are NOT run via
# asyncio.gather — they go through the Redis-backed queue one at a time.
HEAVY_SOURCES = {"eu_funding", "undp_grants", "innovate_uk", "gcf_grants"}

# All static scrapers (37 total)
ALL_STATIC_SCRAPERS = [
    # US Government
    GrantsGovScraper(),
    FederalRegisterScraper(),
    NSFScraper(),
    NASASBIRScraper(),
    NIHSBIRScraper(),
    # International Bodies
    WorldBankScraper(),
    UNDPScraper(),
    GCFScraper(),
    WFPInnovationScraper(),
    WHOInnovationScraper(),
    USAIDCentralAsiaScraper(),
    GatesFoundationScraper(),
    GlobalInnovationFundScraper(),
    # European
    EUFundingScraper(),
    InnovateUKScraper(),
    InnosuisseScraper(),
    InnovationFundDenmarkScraper(),
    # Latin America & Asia
    StartupChileScraper(),
    FAPESPScraper(),
    HongKongITFScraper(),
    KOSGEBScraper(),
    TUBITAKScraper(),
    AstanaHubScraper(),
    # Corporate Programs
    AWSImagineGrantScraper(),
    GoogleForStartupsScraper(),
    MicrosoftForStartupsScraper(),
    NVIDIAInceptionScraper(),
    # Global Accelerators
    AntlerScraper(),
    TechstarsGrantsScraper(),
    IFundWomenScraper(),
    GermanAcceleratorScraper(),
    GISTNetworkScraper(),
    MiskAcceleratorScraper(),
    KAUSTScraper(),
    # Fellowships
    HFSPScraper(),
    SchmidtScienceScraper(),
    QuadFellowshipScraper(),
    BolashaqScraper(),
]


async def bulk_save_grants(db: AsyncSession, grants: list[GrantData]) -> tuple[int, int]:
    """
    Save new grants to DB. Skips duplicates (by source_url).
    Returns (new_count, skipped_count).
    """
    if not grants:
        return 0, 0

    candidate_urls = {g.source_url for g in grants}
    existing = await db.execute(
        select(Grant.source_url).where(Grant.source_url.in_(candidate_urls))
    )
    existing_urls = {row[0] for row in existing}

    def _build(g: GrantData) -> Grant:
        # Populate structured budget fields from grant_amount free-text when the
        # scraper didn't already supply normalized values.
        b_min, b_max, currency = g.budget_min, g.budget_max, g.currency
        if b_min is None and b_max is None and g.grant_amount:
            b_min, b_max, currency = parse_budget(g.grant_amount)
        return Grant(
            title=g.title,
            description=g.description or "",
            organization=g.organization or "",
            country=g.country or "",
            category=g.category or "",
            deadline=g.deadline,
            source_url=g.source_url,
            status="pending",
            ai_score=0.0,
            embedding_status="pending",
            grant_amount=g.grant_amount,
            industry=g.industry,
            budget_min=b_min,
            budget_max=b_max,
            currency=currency or g.currency,
            region=g.region,
        )

    new_grants = [
        _build(g)
        for g in grants
        if g.source_url not in existing_urls
    ]

    if new_grants:
        db.add_all(new_grants)
        await db.flush()

    return len(new_grants), len(grants) - len(new_grants)


async def run_all_scrapers_async(include_ai_agent: bool = True) -> dict:
    """
    Run all scrapers concurrently + AI Search Agent.
    Returns summary dict with counts per source.
    """
    summary: dict = {
        "total": 0, "new": 0, "skipped": 0, "errors": 0,
        "by_source": {}, "last_error": None,
        "ai_agent": {"total": 0, "new": 0, "skipped": 0},
    }

    async def _run_one(scraper):
        try:
            logger.info(f"Scraper: {scraper.name}")
            return scraper.name, await scraper.scrape(), None
        except Exception as e:
            logger.error(f"Scraper {scraper.name} failed: {e}")
            return scraper.name, [], f"[{scraper.name}] {e.__class__.__name__}: {e}"

    # Split light (plain-HTTP/API) vs heavy (stealth browser / adaptive parser).
    light_scrapers = [s for s in ALL_STATIC_SCRAPERS if s.name not in HEAVY_SOURCES]
    heavy_scrapers = {s.name: s for s in ALL_STATIC_SCRAPERS if s.name in HEAVY_SOURCES}

    # Light scrapers run concurrently (cheap I/O).
    scrape_results = list(await asyncio.gather(
        *(_run_one(s) for s in light_scrapers),
        return_exceptions=False,
    ))

    # Heavy scrapers run STRICTLY one-at-a-time via the Redis-backed queue so we
    # never have two camoufox/Firefox sessions resident on the 4 GB VPS.
    if heavy_scrapers:
        from scraping.scrape_queue import ScrapeQueue
        queue = ScrapeQueue()
        try:
            for name in heavy_scrapers:
                await queue.enqueue(name)

            async def _run_by_name(name: str):
                scraper = heavy_scrapers[name]
                return await _run_one(scraper)

            heavy_results = await queue.process(_run_by_name)
            scrape_results.extend(heavy_results)
        finally:
            await queue.close()

    async with AsyncSessionLocal() as db:
        # Save static scraper results
        for source_name, grants, scrape_err in scrape_results:
            source_summary = {"total": len(grants), "new": 0, "skipped": 0, "errors": 0}

            if scrape_err:
                summary["errors"] += 1
                source_summary["errors"] += 1
                if not summary["last_error"]:
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

            summary["by_source"][source_name] = source_summary

        # Run AI Search Agent (Tavily + Firecrawl + NVIDIA LLM)
        if include_ai_agent:
            try:
                from scraping.ai_search_agent import AISearchAgent
                agent = AISearchAgent()
                ai_grants = await agent.discover_grants()

                if ai_grants:
                    new_c, skip_c = await bulk_save_grants(db, ai_grants)
                    await db.commit()
                    summary["ai_agent"] = {
                        "total": len(ai_grants),
                        "new": new_c,
                        "skipped": skip_c,
                    }
                    summary["new"] += new_c
                    summary["total"] += len(ai_grants)
            except Exception as e:
                logger.error(f"AI Search Agent failed: {e}")
                summary["ai_agent"]["error"] = str(e)

    logger.info(f"Scraping complete: {summary['new']} new, {summary['skipped']} skipped, {summary['errors']} errors")
    return summary
