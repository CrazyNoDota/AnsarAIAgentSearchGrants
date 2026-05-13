"""
AI-Powered Grant Discovery Agent

Uses:
  - Tavily API: deep internet search for grant/funding URLs
  - Firecrawl API: clean web content extraction from discovered pages
  - NVIDIA LLM: structured data extraction from raw page content

Runs every 24 hours via n8n workflow.
Discovers new funding opportunities not covered by static scrapers.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import get_settings
from scraping.base_scraper import GrantData

logger = logging.getLogger(__name__)
settings = get_settings()

# Crawl4AI is optional — import lazily so the backend still boots if it's not installed
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    _CRAWL4AI_AVAILABLE = True
except Exception:  # pragma: no cover
    _CRAWL4AI_AVAILABLE = False
    AsyncWebCrawler = BrowserConfig = CrawlerRunConfig = None  # type: ignore

MIN_USEFUL_CONTENT = 600  # below this many chars we treat content as too thin

# Diverse search queries to maximize discovery coverage
DISCOVERY_QUERIES = [
    "startup grants 2026 equity-free funding applications",
    "university research grants funding portal 2026",
    "innovation grants AI technology startups 2026",
    "Central Asia Kazakhstan startup funding programs",
    "NGO funding programs development organizations 2026",
    "student scholarship programs international 2026",
    "government technology grants small business 2026",
    "European innovation fund startups applications open",
    "climate technology green energy grants 2026",
    "social enterprise impact funding programs",
    "research fellowship science programs 2026",
    "women entrepreneur grants funding programs",
    "healthcare innovation grants programs 2026",
    "education technology edtech grants funding",
    "accelerator programs no equity seed funding 2026",
]

# LLM extraction prompt for structured grant data
EXTRACTION_PROMPT = """Extract all grant and funding opportunities from the webpage content below.

Return a JSON array. Each item must have this exact structure:
{
  "title": "Full name of the grant or program",
  "organization": "Funding organization name",
  "country": "Country or region (use 'International' for global programs)",
  "deadline": "Application deadline in YYYY-MM-DD format, or null if not specified",
  "grant_amount": "Funding amount or range (e.g., 'Up to $50,000', '€100K-€500K'), or null",
  "eligibility": "Brief description of who can apply (1-2 sentences)",
  "industry": "Target industry/sector (e.g., 'Technology', 'Healthcare', 'Agriculture')",
  "startup_stage": "Target stage (e.g., 'Early-stage', 'Growth', 'Any') or null",
  "summary": "2-3 sentence description of what the grant supports",
  "application_url": "Direct URL to apply or get more info, or null",
  "category": "One of: University, Startup, NGO, Research, Government, Accelerator, Fellowship, Other"
}

Rules:
- Only include actual grants, funding programs, accelerators, or fellowships
- Skip articles, news, or informational pages without active programs
- If deadline has passed (before 2026-01-01), skip that grant
- Return [] if no valid grants found

Webpage content:"""


class AISearchAgent:
    """Discovers new grant opportunities using Tavily search + Firecrawl + Crawl4AI fallback."""

    def __init__(self):
        self._llm: Optional[AsyncOpenAI] = None
        if settings.nvidia_api_key:
            self._llm = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
            )
        # Reuse a single browser across calls — cheaper than spinning up per URL.
        self._browser: Optional["AsyncWebCrawler"] = None

    async def _ensure_browser(self) -> Optional["AsyncWebCrawler"]:
        """Lazy-init a single Crawl4AI browser. Returns None if Crawl4AI is unavailable."""
        if not _CRAWL4AI_AVAILABLE:
            return None
        if self._browser is not None:
            return self._browser
        try:
            cfg = BrowserConfig(
                headless=True,
                browser_type="chromium",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                viewport_width=1366,
                viewport_height=900,
                ignore_https_errors=True,
            )
            self._browser = AsyncWebCrawler(config=cfg)
            await self._browser.start()
            logger.info("Crawl4AI browser session started")
            return self._browser
        except Exception as e:
            logger.warning(f"Crawl4AI browser failed to start, falling back to httpx only: {e}")
            self._browser = None
            return None

    async def _close_browser(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    async def _crawl4ai_render(self, url: str) -> Optional[str]:
        """Render a URL through a stealth Chromium and return cleaned markdown."""
        browser = await self._ensure_browser()
        if browser is None:
            return None
        try:
            run_cfg = CrawlerRunConfig(
                word_count_threshold=20,
                page_timeout=45000,
                wait_for_images=False,
                exclude_external_links=True,
                exclude_social_media_links=True,
                remove_overlay_elements=True,
            )
            result = await asyncio.wait_for(
                browser.arun(url=url, config=run_cfg), timeout=60
            )
            if not result or not getattr(result, "success", False):
                return None
            md = getattr(result, "markdown", None) or getattr(result, "cleaned_html", None) or ""
            # Crawl4AI sometimes returns a MarkdownGenerationResult object
            if hasattr(md, "raw_markdown"):
                md = md.raw_markdown or ""
            return md if isinstance(md, str) and md.strip() else None
        except Exception as e:
            logger.warning(f"Crawl4AI render failed for {url}: {e}")
            return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    async def _tavily_search(self, query: str, max_results: int = 5) -> list[dict]:
        """Search the internet using Tavily API. Returns result list with URLs + content."""
        if not settings.use_tavily:
            return []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_raw_content": True,
                        "max_results": max_results,
                        "exclude_domains": [
                            "reddit.com", "twitter.com", "youtube.com",
                            "facebook.com", "instagram.com", "linkedin.com",
                        ],
                    },
                    timeout=30,
                )
                response.raise_for_status()
                return response.json().get("results", [])
        except Exception as e:
            logger.error(f"Tavily search failed for '{query}': {e}")
            return []

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    async def _firecrawl_scrape(self, url: str) -> Optional[str]:
        """Extract clean markdown content from URL using Firecrawl."""
        if not settings.use_firecrawl:
            return None

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    headers={"Authorization": f"Bearer {settings.firecrawl_api_key}"},
                    json={
                        "url": url,
                        "formats": ["markdown"],
                        "onlyMainContent": True,
                        "excludeTags": ["nav", "footer", "header", "aside"],
                    },
                    timeout=45,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("success"):
                    return data.get("data", {}).get("markdown", "")
        except Exception as e:
            logger.error(f"Firecrawl scrape failed for {url}: {e}")
        return None

    async def _extract_grants_llm(self, content: str, source_url: str) -> list[GrantData]:
        """Use NVIDIA LLM to extract structured grant data from raw page content."""
        if not self._llm or not content.strip():
            return []

        # Truncate content to avoid token limits
        truncated = content[:7000]

        try:
            response = await self._llm.chat.completions.create(
                model=settings.nvidia_model,
                messages=[{
                    "role": "user",
                    "content": f"{EXTRACTION_PROMPT}\n\n{truncated}",
                }],
                temperature=0.1,
                max_tokens=2500,
                timeout=60,
            )

            raw_text = response.choices[0].message.content or ""

            # Parse JSON array from response
            start = raw_text.find("[")
            end = raw_text.rfind("]")
            if start == -1 or end == -1:
                return []

            grants_json = json.loads(raw_text[start:end + 1])
            if not isinstance(grants_json, list):
                return []

            results: list[GrantData] = []
            for g in grants_json:
                if not isinstance(g, dict) or not g.get("title"):
                    continue

                # Parse deadline date
                deadline = None
                if g.get("deadline"):
                    try:
                        deadline = datetime.strptime(g["deadline"], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass

                # Build enriched description including extracted fields
                desc_parts = []
                if g.get("summary"):
                    desc_parts.append(g["summary"])
                if g.get("eligibility"):
                    desc_parts.append(f"Eligibility: {g['eligibility']}")
                if g.get("grant_amount"):
                    desc_parts.append(f"Funding: {g['grant_amount']}")

                results.append(GrantData(
                    title=str(g.get("title", ""))[:512],
                    description="\n".join(desc_parts),
                    organization=str(g.get("organization", ""))[:255],
                    country=str(g.get("country", ""))[:255],
                    category=str(g.get("category", "Other"))[:255],
                    deadline=deadline,
                    source_url=str(g.get("application_url") or source_url)[:2000],
                ))

            return results

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"LLM extraction failed for {source_url}: {e}")
            return []

    async def discover_grants(
        self,
        queries: Optional[list[str]] = None,
        max_queries: int = 8,
        max_results_per_query: int = 4,
    ) -> list[GrantData]:
        """
        Full discovery pipeline (three-layer fetch with graceful degradation):
        1. Tavily search returns candidate URLs (+ best-effort raw_content)
        2. If content is thin, Firecrawl scrapes a clean version
        3. If still thin, Crawl4AI stealth-browser renders the page
        4. NVIDIA LLM extracts structured GrantData
        5. Return deduplicated GrantData list

        Called by n8n daily workflow.
        """
        if not settings.use_tavily:
            logger.warning("AI Search Agent: Tavily key required for URL discovery — skipping")
            return []

        search_queries = (queries or DISCOVERY_QUERIES)[:max_queries]
        seen_urls: set[str] = set()
        all_grants: list[GrantData] = []

        # Counters so we can see how often each fallback layer helped
        fallback_stats = {"tavily": 0, "firecrawl": 0, "crawl4ai": 0, "skipped": 0}

        try:
            for query in search_queries:
                logger.info(f"AI Search Agent: searching '{query}'")
                results = await self._tavily_search(query, max_results=max_results_per_query)

                for result in results:
                    url = result.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # Layer 1: Tavily raw_content
                    content = result.get("raw_content") or result.get("content", "") or ""
                    source_layer = "tavily" if len(content) >= MIN_USEFUL_CONTENT else None

                    # Layer 2: Firecrawl
                    if (not source_layer) and settings.use_firecrawl:
                        crawled = await self._firecrawl_scrape(url)
                        if crawled and len(crawled) > len(content):
                            content = crawled
                            if len(content) >= MIN_USEFUL_CONTENT:
                                source_layer = "firecrawl"

                    # Layer 3: Crawl4AI stealth browser render
                    if not source_layer:
                        rendered = await self._crawl4ai_render(url)
                        if rendered and len(rendered) > len(content):
                            content = rendered
                            if len(content) >= MIN_USEFUL_CONTENT:
                                source_layer = "crawl4ai"

                    if not source_layer or len(content) < 200:
                        fallback_stats["skipped"] += 1
                        continue

                    fallback_stats[source_layer] += 1
                    grants = await self._extract_grants_llm(content, url)
                    if grants:
                        logger.info(f"  [{source_layer}] Extracted {len(grants)} grant(s) from {url}")
                    all_grants.extend(grants)
        finally:
            await self._close_browser()

        # Deduplicate by title similarity (simple)
        unique_grants: list[GrantData] = []
        seen_titles: set[str] = set()
        for g in all_grants:
            key = g.title.lower()[:50]
            if key not in seen_titles:
                seen_titles.add(key)
                unique_grants.append(g)

        logger.info(
            f"AI Search Agent: discovered {len(unique_grants)} unique grants "
            f"from {len(seen_urls)} URLs across {len(search_queries)} queries "
            f"(layers: {fallback_stats})"
        )
        return unique_grants
