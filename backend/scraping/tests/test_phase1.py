"""
Phase 1 smoke / unit tests — no live network, no real LLM, no real browser.

Run from the backend dir:
    python -m pytest scraping/tests/test_phase1.py -v
or standalone:
    python scraping/tests/test_phase1.py

Proves:
  1. All new Phase 1 modules import cleanly (even without camoufox/playwright).
  2. apply_strategy() extracts grants from a saved HTML fixture (the cached-parser
     path that runs WITHOUT the LLM).
  3. The AdaptiveParser LLM->strategy->cache loop works against the fixture using
     a STUB NIM client (so the parser-generation logic is exercised offline) and
     the generated strategy is reused from cache on the second call.
  4. parse_budget() normalizes free-text amounts.
  5. ScrapeQueue processes jobs strictly one-at-a-time (FIFO) via the in-process
     fallback (no Redis required).
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Make `backend/` importable when run standalone.
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

FIXTURE = Path(__file__).parent / "fixtures" / "sample_grants_list.html"

# Known-good strategy for the fixture (what an LLM would produce).
FIXTURE_STRATEGY = {
    "item_selector": "li.call-card",
    "fields": {
        "title": {"selector": "a.call-title", "attr": None},
        "url": {"selector": "a.call-title", "attr": "href"},
        "deadline": {"selector": "time.call-deadline", "attr": None},
        "organization": {"selector": "div.call-org", "attr": None},
        "description": {"selector": "p.call-desc", "attr": None},
        "amount": {"selector": "span.call-amount", "attr": None},
        "region": {"selector": "span.call-region", "attr": None},
        "industry": {"selector": "span.call-industry", "attr": None},
    },
}

# A strategy whose item_selector matches nothing on the fixture (a "stale" /
# drifted strategy that extracts 0 grants).
STALE_STRATEGY = {
    "item_selector": "div.OLD-layout-card",
    "fields": {"title": {"selector": "a", "attr": None},
               "url": {"selector": "a", "attr": "href"}},
}


def test_imports():
    import scraping.stealth_browser as sb
    import scraping.nim_client as nc
    import scraping.parser_cache as pc
    import scraping.adaptive_parser as ap
    import scraping.scrape_queue as sq
    import scraping.budget_parser as bp
    import scraping.gcf_grants as gcf
    import scraping.base_scraper as base
    # stealth_available is a cheap, side-effect-free check.
    assert isinstance(sb.stealth_available(), bool)
    # base_scraper now exposes the stealth opt-in API.
    assert hasattr(base.BaseScraper, "fetch")
    assert hasattr(base.GrantData, "budget_min")
    print("OK imports")


def test_apply_strategy():
    from scraping.adaptive_parser import apply_strategy
    html = FIXTURE.read_text(encoding="utf-8")
    grants = apply_strategy(
        html, FIXTURE_STRATEGY,
        default_org="Fallback Org",
        default_country="International",
        base_url="https://portal.example",
    )
    assert len(grants) == 3, f"expected 3 grants, got {len(grants)}"
    titles = {g.title for g in grants}
    assert "Green Energy Innovation Grant 2026" in titles
    # Relative URL got absolutized; absolute URL preserved.
    urls = {g.source_url for g in grants}
    assert "https://portal.example/calls/green-energy-2026" in urls
    assert "https://example.org/calls/agri-fund" in urls
    # Deadline parsed to a date.
    by_title = {g.title: g for g in grants}
    assert str(by_title["Digital Health Accelerator"].deadline) == "2026-07-15"
    assert by_title["Smart Agriculture Fund"].organization == "UNDP"
    print("OK apply_strategy ->", len(grants), "grants")


class _StubNIM:
    """Pretends to be NIMClient; returns the fixture strategy as JSON once."""
    def __init__(self):
        self.available = True
        self.calls = 0

    async def chat(self, prompt, **kwargs):
        self.calls += 1
        # The strategy prompt comes first; return the strategy JSON.
        return json.dumps(FIXTURE_STRATEGY)


def test_adaptive_loop_learns_and_caches():
    from scraping.adaptive_parser import AdaptiveParser
    from scraping.parser_cache import ParserCache

    async def _run():
        html = FIXTURE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PARSER_CACHE_DIR"] = tmp
            # Force the file-fallback cache (no Redis) by pointing at a fresh dir.
            cache = ParserCache()
            cache._redis = None  # ensure file fallback path is exercised
            stub = _StubNIM()
            parser = AdaptiveParser(nim=stub, cache=cache)

            # First call: no cached strategy -> LLM generates one -> grants + cache.
            grants1 = await parser.parse(
                "unit_source", html,
                default_org="X", base_url="https://portal.example",
            )
            assert len(grants1) == 3, f"first parse got {len(grants1)}"
            assert stub.calls == 1, "LLM should be called once to learn"

            # Strategy persisted to the file cache.
            cached = await cache.get("unit_source")
            assert cached and cached.get("item_selector") == "li.call-card"

            # Second call (fresh parser, same cache dir): served from cache, NO LLM.
            stub2 = _StubNIM()
            parser2 = AdaptiveParser(nim=stub2, cache=ParserCache())
            parser2.cache._redis = None
            grants2 = await parser2.parse(
                "unit_source", html, base_url="https://portal.example",
            )
            assert len(grants2) == 3, f"cached parse got {len(grants2)}"
            assert stub2.calls == 0, "cached strategy must not call the LLM"
            await parser.close()
        os.environ.pop("PARSER_CACHE_DIR", None)

    asyncio.run(_run())
    print("OK adaptive loop learns + caches (LLM called once, then served from cache)")


def test_budget_parser():
    from scraping.budget_parser import parse_budget
    assert parse_budget("Up to $50,000") == (None, 50000.0, "USD")
    lo, hi, cur = parse_budget("€100K-€500K")
    assert (lo, hi, cur) == (100000.0, 500000.0, "EUR")
    lo, hi, cur = parse_budget("GBP 2 million")
    assert (lo, hi, cur) == (2000000.0, 2000000.0, "GBP")
    assert parse_budget("") == (None, None, None)
    assert parse_budget(None) == (None, None, None)
    print("OK budget parser")


def test_scrape_queue_sequential():
    from scraping.scrape_queue import ScrapeQueue

    async def _run():
        q = ScrapeQueue()
        q._redis = None  # force in-process queue (no Redis dependency)
        for name in ["a", "b", "c"]:
            await q.enqueue(name)

        order = []

        async def run_one(name):
            order.append(("start", name))
            await asyncio.sleep(0)  # yield; if concurrent, interleaving would show
            order.append(("end", name))
            return name, [], None

        results = await q.process(run_one)
        await q.close()
        # Strictly sequential: each job fully finishes before the next starts.
        assert order == [
            ("start", "a"), ("end", "a"),
            ("start", "b"), ("end", "b"),
            ("start", "c"), ("end", "c"),
        ], order
        assert [r[0] for r in results] == ["a", "b", "c"]

    asyncio.run(_run())
    print("OK scrape queue sequential FIFO")


# ── Fix 3: cache invalidation + don't-cache-zero-result ──────────────────────
def test_stale_strategy_invalidated_and_relearned():
    """A cached strategy returning 0 is DELETED, then re-learned from the LLM."""
    from scraping.adaptive_parser import AdaptiveParser
    from scraping.parser_cache import ParserCache

    async def _run():
        html = FIXTURE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PARSER_CACHE_DIR"] = tmp
            cache = ParserCache()
            cache._redis = None
            # Seed a STALE strategy that matches nothing.
            await cache.set("stale_source", STALE_STRATEGY)
            assert (await cache.get("stale_source"))["item_selector"] == "div.OLD-layout-card"

            stub = _StubNIM()  # will return the good FIXTURE_STRATEGY on re-learn
            parser = AdaptiveParser(nim=stub, cache=cache)
            grants = await parser.parse(
                "stale_source", html, base_url="https://portal.example",
            )
            # Re-learned the good strategy -> 3 grants, LLM called once.
            assert len(grants) == 3, f"expected 3 after relearn, got {len(grants)}"
            assert stub.calls == 1, "LLM should be called once to re-learn"
            # The stale strategy was replaced by the good one (not the old selector).
            cached = await cache.get("stale_source")
            assert cached and cached["item_selector"] == "li.call-card", \
                "stale strategy should have been invalidated + replaced"
            await parser.close()
        os.environ.pop("PARSER_CACHE_DIR", None)

    asyncio.run(_run())
    print("OK stale strategy invalidated + re-learned")


class _ZeroNIM:
    """Returns a strategy that always extracts 0 grants (selector matches nothing)."""
    def __init__(self):
        self.available = True
        self.calls = 0

    async def chat(self, prompt, **kwargs):
        self.calls += 1
        # Strategy prompt -> a non-matching selector; direct prompt -> empty array.
        if "JSON array" in prompt:
            return "[]"
        return json.dumps(STALE_STRATEGY)


def test_zero_result_strategy_not_cached():
    """A learned strategy that extracts 0 grants must NOT be cached."""
    from scraping.adaptive_parser import AdaptiveParser
    from scraping.parser_cache import ParserCache

    async def _run():
        html = FIXTURE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PARSER_CACHE_DIR"] = tmp
            cache = ParserCache()
            cache._redis = None
            parser = AdaptiveParser(nim=_ZeroNIM(), cache=cache)
            grants = await parser.parse("zero_source", html)
            assert grants == [], f"expected 0 grants, got {len(grants)}"
            # Nothing was cached because the strategy extracted 0.
            assert await cache.get("zero_source") is None, \
                "a 0-result strategy must not be cached"
            await parser.close()
        os.environ.pop("PARSER_CACHE_DIR", None)

    asyncio.run(_run())
    print("OK zero-result strategy not cached")


# ── Fix 4: budget / region / industry populated from a fixture ───────────────
def test_structured_fields_populated():
    """Adaptive parser fills budget/region/industry into GrantData from a fixture."""
    from scraping.adaptive_parser import AdaptiveParser
    from scraping.parser_cache import ParserCache

    async def _run():
        html = FIXTURE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PARSER_CACHE_DIR"] = tmp
            cache = ParserCache()
            cache._redis = None
            parser = AdaptiveParser(nim=_StubNIM(), cache=cache)
            grants = await parser.parse(
                "struct_source", html, base_url="https://portal.example",
            )
            by_title = {g.title: g for g in grants}
            g = by_title["Green Energy Innovation Grant 2026"]
            assert g.grant_amount == "Up to $500,000", g.grant_amount
            assert g.region == "Global", g.region
            assert g.industry == "Climate / Green Energy", g.industry
            # Free-text amount normalized into structured budget fields.
            assert g.budget_max == 500000.0, g.budget_max
            assert g.budget_min is None, g.budget_min
            assert g.currency == "USD", g.currency
            await parser.close()
        os.environ.pop("PARSER_CACHE_DIR", None)

    asyncio.run(_run())
    print("OK structured budget/region/industry populated")


# ── Fix 5: HTTP fallback when the stealth path raises a runtime browser error ─
def test_stealth_runtime_error_falls_back_to_http():
    """A stealth runtime crash degrades to the cheap HTTP path (not empty)."""
    import scraping.base_scraper as base
    from scraping.base_scraper import BaseScraper

    class _Scraper(BaseScraper):
        name = "fallback_test"
        async def scrape(self):
            return []

    async def _run():
        scraper = _Scraper()

        # Patch the stealth fetch to raise a runtime browser error (not
        # StealthUnavailable) and the HTTP client to return a sentinel body.
        import scraping.stealth_browser as sb

        async def _boom(*a, **k):
            raise RuntimeError("camoufox page crashed / navigation timeout")

        orig_fetch = sb.fetch_html
        sb.fetch_html = _boom
        # base_scraper imports fetch_html lazily from the module, so patching the
        # module attribute is enough.

        import httpx

        class _FakeResp:
            text = "<html>http-fallback-body</html>"
            def raise_for_status(self):  # noqa: D401
                return None

        class _FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                return _FakeResp()

        orig_client = httpx.AsyncClient
        httpx.AsyncClient = _FakeClient
        try:
            html = await scraper.fetch("https://example.com", stealth=True)
            assert html == "<html>http-fallback-body</html>", html
        finally:
            sb.fetch_html = orig_fetch
            httpx.AsyncClient = orig_client

    asyncio.run(_run())
    print("OK stealth runtime error falls back to HTTP")


# ── Fix 2: Redis distributed lock serializes overlapping processors ──────────
class _FakeRedis:
    """Minimal async Redis stub implementing SET NX PX, eval (CAS-del), lpop."""
    def __init__(self, store, queue):
        self._store = store      # shared dict (the lock key lives here)
        self._queue = queue      # shared list (the job queue)

    async def set(self, key, val, nx=False, px=None):
        if nx and key in self._store:
            return None
        self._store[key] = val
        return True

    async def eval(self, script, numkeys, key, token):
        # Compare-and-delete release.
        if self._store.get(key) == token:
            del self._store[key]
            return 1
        return 0

    async def rpush(self, key, val):
        self._queue.append(val)
        return len(self._queue)

    async def lpop(self, key):
        return self._queue.pop(0) if self._queue else None

    async def delete(self, key):
        self._store.pop(key, None)
        return 1

    async def aclose(self):
        return None


def test_redis_lock_serializes_processors():
    """Two overlapping processors sharing one Redis: only one drains at a time."""
    from scraping.scrape_queue import ScrapeQueue

    async def _run():
        shared_store: dict = {}
        shared_queue: list = []

        def _make_queue():
            q = ScrapeQueue()
            q._redis = _FakeRedis(shared_store, shared_queue)
            return q

        # Enqueue some jobs on the shared queue.
        producer = _make_queue()
        for name in ["a", "b", "c", "d"]:
            await producer.enqueue(name)

        q1 = _make_queue()
        q2 = _make_queue()

        active = {"count": 0, "max": 0}

        async def run_one(name):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            await asyncio.sleep(0)  # yield so overlap would be observable
            active["count"] -= 1
            return name, [], None

        # Run both processors concurrently against the SAME Redis lock + queue.
        r1, r2 = await asyncio.gather(q1.process(run_one), q2.process(run_one))
        await q1.close()
        await q2.close()
        await producer.close()

        # The distributed lock means only one processor ever ran jobs at a time.
        assert active["max"] == 1, f"processors overlapped (max concurrent={active['max']})"
        # One processor got the lock + drained all 4; the other got the lock
        # afterward but found an empty queue. Together they cover all 4 jobs.
        names = sorted(n for n, _, _ in (r1 + r2))
        assert names == ["a", "b", "c", "d"], names
        # The lock key was released (compare-and-del) — not left dangling.
        assert "grant_scrape:processor_lock" not in shared_store

    asyncio.run(_run())
    print("OK redis distributed lock serializes overlapping processors")


# ── Fix 1: migration 004 hygiene (static source check, no DB) ────────────────
def test_migration_004_does_not_touch_deadline_index():
    """004 upgrade must NOT (re)create ix_grants_deadline; downgrade drops only
    Phase-1-owned objects."""
    import ast
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "004_phase1_filters.py")
    src = mig.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _index_calls(func_name, kind):
        """Collect index names passed to op.create_index/op.drop_index inside func."""
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == kind
                            and call.args
                            and isinstance(call.args[0], ast.Constant)):
                        names.append(call.args[0].value)
        return names

    upgrade_creates = _index_calls("upgrade", "create_index")
    downgrade_drops = _index_calls("downgrade", "drop_index")

    # upgrade must NOT (re)create the pre-existing deadline index.
    assert "ix_grants_deadline" not in upgrade_creates, \
        "004 upgrade must not recreate ix_grants_deadline (owned by 001)"
    # downgrade must NOT drop the pre-existing deadline index.
    assert "ix_grants_deadline" not in downgrade_drops, \
        "004 downgrade must not drop ix_grants_deadline (owned by 001)"
    # downgrade should drop only Phase-1-owned indexes.
    phase1_indexes = {"ix_grants_region", "ix_grants_budget_max", "ix_grants_industry"}
    assert set(downgrade_drops) == phase1_indexes, downgrade_drops
    # revision chain is linear 003 -> 004.
    assert "down_revision = '003_rag_learning'" in src
    print("OK migration 004 leaves ix_grants_deadline alone")


def _main():
    test_imports()
    test_apply_strategy()
    test_adaptive_loop_learns_and_caches()
    test_budget_parser()
    test_scrape_queue_sequential()
    test_stale_strategy_invalidated_and_relearned()
    test_zero_result_strategy_not_cached()
    test_structured_fields_populated()
    test_stealth_runtime_error_falls_back_to_http()
    test_redis_lock_serializes_processors()
    test_migration_004_does_not_touch_deadline_index()
    print("\nALL PHASE 1 SMOKE TESTS PASSED")


if __name__ == "__main__":
    _main()
