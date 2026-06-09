"""
Adaptive LLM parser loop (Phase 1).

For fragile sources, this implements:

    LLM reads a page  ->  writes an extraction strategy (CSS selectors as JSON)
                      ->  strategy is cached per-source (Redis / file fallback)
                      ->  on later runs the cached strategy is applied with
                          BeautifulSoup, NO LLM call needed.

If applying the cached strategy yields nothing (page drifted), the strategy is
invalidated and re-learned. As a final fallback the parser can ask the LLM to
extract grants directly from the page text (same contract as ai_search_agent),
which is robust but more expensive — so it is only used when the
selector-strategy path fails.

The LLM is **NVIDIA NIM Chat Completions, called directly** (see nim_client.py),
NOT Webwright — per the Phase 0 finding that Webwright->NIM is wire-incompatible.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from scraping.base_scraper import GrantData
from scraping.budget_parser import parse_budget
from scraping.nim_client import NIMClient
from scraping.parser_cache import ParserCache

logger = logging.getLogger(__name__)

# Cap how many times we re-learn a strategy for one parse() call so a
# permanently-broken page can't spin in an infinite LLM loop.
MAX_RELEARN_ATTEMPTS = 1


# ── Prompt 1: generate a reusable selector strategy ──────────────────────────
STRATEGY_PROMPT = """You are a web-scraping expert. Below is the HTML of a page \
that lists grant / funding opportunities. Produce a REUSABLE extraction strategy \
as JSON so a program can extract every opportunity WITHOUT calling an LLM again.

Return ONLY a JSON object with this exact shape:
{
  "item_selector": "CSS selector matching the repeating container for ONE opportunity",
  "fields": {
    "title":       {"selector": "CSS selector relative to item", "attr": null},
    "url":         {"selector": "CSS selector for the link", "attr": "href"},
    "deadline":    {"selector": "CSS selector or null", "attr": null},
    "organization":{"selector": "CSS selector or null", "attr": null},
    "description": {"selector": "CSS selector or null", "attr": null},
    "amount":      {"selector": "CSS selector or null", "attr": null},
    "region":      {"selector": "CSS selector or null", "attr": null},
    "industry":    {"selector": "CSS selector or null", "attr": null}
  }
}

Rules:
- "attr": null means take the element's text; otherwise take that HTML attribute.
- Selectors must be valid CSS usable by BeautifulSoup's .select().
- Prefer stable class/structure selectors over nth-child where possible.
- "amount" is the funding amount/value, "region" is the geography, "industry" is
  the sector/theme — include them only if present on the page, else use null.
- If the page has no list of opportunities, return {"item_selector": null}.

HTML:
"""

# ── Prompt 2: direct extraction fallback (robust, expensive) ─────────────────
DIRECT_PROMPT = """Extract all grant / funding opportunities from the page content \
below. Return ONLY a JSON array. Each item:
{
  "title": "...",
  "organization": "...",
  "country": "... or null",
  "deadline": "YYYY-MM-DD or null",
  "description": "1-2 sentences or null",
  "url": "direct link or null",
  "amount": "funding amount as free text (e.g. 'Up to $50,000') or null",
  "region": "geographic region (e.g. 'Europe') or null",
  "industry": "sector / theme (e.g. 'Climate') or null"
}
Return [] if none found.

Content:
"""


def _parse_deadline(value) -> Optional[datetime.date]:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt).date()
        except (ValueError, TypeError):
            continue
    # last resort: pull a YYYY-MM-DD substring
    import re
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _extract_json(text: str, kind: str):
    """Pull a JSON object/array out of an LLM reply."""
    if not text:
        return None
    if kind == "array":
        a, b = text.find("["), text.rfind("]")
    else:
        a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def apply_strategy(html: str, strategy: dict, *, default_org: str = "",
                   default_country: Optional[str] = None,
                   base_url: str = "") -> list[GrantData]:
    """Apply a cached selector strategy to HTML using BeautifulSoup. Pure, no LLM."""
    from bs4 import BeautifulSoup

    item_sel = (strategy or {}).get("item_selector")
    if not item_sel:
        return []
    fields = strategy.get("fields", {})
    soup = BeautifulSoup(html, "html.parser")
    out: list[GrantData] = []

    def _get(node, spec):
        if not spec or not spec.get("selector"):
            return None
        el = node.select_one(spec["selector"])
        if el is None:
            return None
        attr = spec.get("attr")
        if attr:
            return el.get(attr)
        return el.get_text(" ", strip=True)

    for node in soup.select(item_sel):
        title = _get(node, fields.get("title"))
        url = _get(node, fields.get("url"))
        if not title or not url:
            continue
        if base_url and url.startswith("/"):
            url = base_url.rstrip("/") + url
        amount = _get(node, fields.get("amount"))
        region = _get(node, fields.get("region"))
        industry = _get(node, fields.get("industry"))
        grant = GrantData(
            title=title.strip()[:512],
            source_url=url.strip(),
            organization=(_get(node, fields.get("organization")) or default_org)[:255],
            description=(_get(node, fields.get("description")) or "")[:1500],
            country=default_country,
            category=None,
            deadline=_parse_deadline(_get(node, fields.get("deadline"))),
            grant_amount=(amount.strip()[:256] if amount else None),
            region=(region.strip()[:128] if region else None),
            industry=(industry.strip()[:256] if industry else None),
        )
        # Normalize free-text amount into structured budget fields.
        if grant.grant_amount:
            grant.budget_min, grant.budget_max, grant.currency = parse_budget(grant.grant_amount)
        out.append(grant)
    return out


class AdaptiveParser:
    """LLM-writes-the-parser loop with per-source strategy caching."""

    def __init__(self, nim: Optional[NIMClient] = None, cache: Optional[ParserCache] = None):
        self.nim = nim or NIMClient()
        self.cache = cache or ParserCache()

    async def parse(
        self,
        source: str,
        html: str,
        *,
        default_org: str = "",
        default_country: Optional[str] = None,
        base_url: str = "",
        force_relearn: bool = False,
    ) -> list[GrantData]:
        """Return GrantData from `html` for `source`, learning+caching a strategy.

        On a cached strategy that yields 0 (page drifted) the stale strategy is
        INVALIDATED (deleted) before re-learning, so the bad cache path isn't
        repeated forever. A NEW strategy is cached only if it extracts >0 grants.
        ``MAX_RELEARN_ATTEMPTS`` bounds the LLM re-learn loop.
        """
        # 1. Try the cached strategy first (no LLM).
        if not force_relearn:
            strategy = await self.cache.get(source)
            if strategy:
                grants = apply_strategy(
                    html, strategy, default_org=default_org,
                    default_country=default_country, base_url=base_url,
                )
                if grants:
                    logger.info("[adaptive:%s] cached strategy -> %d grants", source, len(grants))
                    return grants
                # Stale strategy: invalidate it BEFORE re-learning so the dead
                # cache path + LLM call isn't repeated on every later run.
                logger.info("[adaptive:%s] cached strategy yielded 0; invalidating + re-learning",
                            source)
                await self.cache.invalidate(source)

        # 2. Ask the LLM to write a reusable strategy (bounded re-learn loop).
        if self.nim.available:
            for attempt in range(1, MAX_RELEARN_ATTEMPTS + 1):
                reply = await self.nim.chat(STRATEGY_PROMPT + html[:14000], max_tokens=900)
                strategy = _extract_json(reply or "", "object")
                if strategy and strategy.get("item_selector"):
                    grants = apply_strategy(
                        html, strategy, default_org=default_org,
                        default_country=default_country, base_url=base_url,
                    )
                    # Only cache a strategy that actually extracts grants.
                    if grants:
                        await self.cache.set(source, strategy)
                        logger.info("[adaptive:%s] learned strategy -> %d grants (cached)",
                                    source, len(grants))
                        return grants
                    logger.info("[adaptive:%s] learned strategy extracted 0 (attempt %d/%d); "
                                "NOT caching", source, attempt, MAX_RELEARN_ATTEMPTS)

            # 3. Direct-extraction fallback (robust, not cached as a selector).
            reply = await self.nim.chat(DIRECT_PROMPT + html[:9000], max_tokens=2500)
            arr = _extract_json(reply or "", "array")
            if isinstance(arr, list):
                out: list[GrantData] = []
                for g in arr:
                    if not isinstance(g, dict) or not g.get("title"):
                        continue
                    grant = GrantData(
                        title=str(g["title"])[:512],
                        source_url=str(g.get("url") or base_url or source)[:2000],
                        organization=str(g.get("organization") or default_org)[:255],
                        description=str(g.get("description") or "")[:1500],
                        country=str(g.get("country") or default_country or "") or None,
                        category=None,
                        deadline=_parse_deadline(g.get("deadline")),
                        grant_amount=(str(g["amount"])[:256] if g.get("amount") else None),
                        region=(str(g["region"])[:128] if g.get("region") else None),
                        industry=(str(g["industry"])[:256] if g.get("industry") else None),
                    )
                    if grant.grant_amount:
                        grant.budget_min, grant.budget_max, grant.currency = parse_budget(
                            grant.grant_amount
                        )
                    out.append(grant)
                logger.info("[adaptive:%s] direct LLM extraction -> %d grants", source, len(out))
                return out

        logger.warning("[adaptive:%s] no grants extracted (LLM available=%s)",
                        source, self.nim.available)
        return []

    async def close(self) -> None:
        await self.cache.close()
