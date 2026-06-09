"""
Phase 7 — OFFLINE unit tests (no live network/LLM, no real DB).

What is proven OFFLINE here:
  1. The CustomSource model is registered in models/__init__ and has the expected
     columns (unique url, enabled default, last_* health fields); to_dict() is a
     plain serializable mapping.
  2. Migration 010 is ADDITIVE (creates only custom_sources + its unique url
     index), chained after 009, and REVERSIBLE (downgrade drops only that table).
  3. The scraper runner exposes run_custom_sources_async, and
     run_all_scrapers_async wires custom sources into the summary (additive — it
     never breaks the static/AI save path).
  4. The /scraper source CRUD endpoints are registered, and SourceCreate rejects
     non-http(s) URLs while accepting valid ones (trimming optional fields).
  5. CustomSourceScraper derives the site ORIGIN for relative-link resolution and
     hands the fetched HTML to the AdaptiveParser unchanged (stub parser, no LLM).

Run from the backend dir:
    python tests/test_phase7.py
or under pytest:
    python -m pytest tests/test_phase7.py -v
"""
import ast
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Make `backend/` importable when run standalone + give the lazy async engine a
# parseable URL (no connection is opened at import time).
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")


# ── 1. Model ─────────────────────────────────────────────────────────────────

def test_model_registered_and_columns():
    import models
    from models.custom_source import CustomSource

    assert "CustomSource" in models.__all__
    assert getattr(models, "CustomSource") is CustomSource

    cols = CustomSource.__table__.columns
    for name in (
        "id", "url", "name", "country", "added_by", "enabled",
        "last_scraped_at", "last_status", "last_count", "last_error",
        "created_at", "updated_at",
    ):
        assert name in cols, f"missing column {name}"

    assert cols["url"].unique is True
    assert cols["url"].nullable is False
    assert cols["enabled"].nullable is False
    print("OK CustomSource model registered + columns present")


def test_to_dict_is_plain():
    from models.custom_source import CustomSource

    s = CustomSource(id=3, url="https://x.io/g", name="X", enabled=True, last_count=0)
    d = s.to_dict()
    assert d["id"] == 3 and d["url"] == "https://x.io/g" and d["name"] == "X"
    assert d["enabled"] is True
    # None datetimes serialize to None (not a datetime object).
    assert d["last_scraped_at"] is None and d["created_at"] is None
    print("OK to_dict() is a plain serializable mapping")


# ── 2. Migration 010 (AST, additive + reversible + chained) ──────────────────

def _migration_src() -> str:
    p = (
        _BACKEND / "database" / "migrations" / "versions"
        / "010_phase7_custom_sources.py"
    )
    return p.read_text(encoding="utf-8")


def test_migration_chained_and_additive():
    src = _migration_src()
    mod = ast.parse(src)
    g = {n.targets[0].id: n.value for n in mod.body
         if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert ast.literal_eval(g["revision"]) == "010_phase7_custom_sources"
    assert ast.literal_eval(g["down_revision"]) == "009_phase5_knowledge_base"

    up = src.split("def upgrade")[1].split("def downgrade")[0]
    # Only the one new table is created; nothing existing is altered/dropped.
    assert "create_table(\n        'custom_sources'" in up
    assert "ix_custom_sources_url" in up and "unique=True" in up
    for forbidden in ("drop_table", "drop_column", "alter_column"):
        assert forbidden not in up, f"upgrade must be additive, found {forbidden}"

    down = src.split("def downgrade")[1]
    assert "drop_table('custom_sources')" in down
    assert "drop_index('ix_custom_sources_url'" in down
    # Downgrade touches ONLY this table.
    assert "knowledge" not in down and "grants" not in down
    print("OK migration 010 additive, reversible, chained after 009")


# ── 3. Runner integration ────────────────────────────────────────────────────

def test_runner_exposes_and_wires_custom_sources():
    import scraping.runner as r
    assert hasattr(r, "run_custom_sources_async")

    src = (_BACKEND / "scraping" / "runner.py").read_text(encoding="utf-8")
    body = src.split("async def run_all_scrapers_async")[1].split(
        "async def run_custom_sources_async"
    )[0]
    # The orchestrator records custom sources in its summary + calls the helper.
    assert '"custom_sources"' in body
    assert "run_custom_sources_async(" in body
    print("OK runner exposes + wires run_custom_sources_async")


# ── 4. Routes + URL validation ───────────────────────────────────────────────

def test_source_routes_registered():
    import api.routes.scraper as s
    paths = {getattr(r, "path", "") for r in s.router.routes}
    for p in (
        "/scraper/sources",
        "/scraper/sources/{source_id}",
        "/scraper/sources/{source_id}/run",
        "/scraper/sources/{source_id}/toggle",
    ):
        assert p in paths, f"missing route {p}"
    print("OK custom-source CRUD routes registered")


def test_source_create_validates_url():
    from api.routes.scraper import SourceCreate

    ok = SourceCreate(url="  https://astanahub.com/en/grants  ", name="  KZ  ")
    assert ok.url == "https://astanahub.com/en/grants"  # trimmed
    assert ok.name == "KZ"  # trimmed

    assert SourceCreate(url="http://x.io/g", name="   ").name is None  # blank -> None

    for bad in ("not a url", "ftp://x.io/file", "javascript:alert(1)", "  "):
        try:
            SourceCreate(url=bad)
        except Exception:
            pass
        else:
            raise AssertionError(f"expected rejection for {bad!r}")
    print("OK SourceCreate validates http(s) URLs + trims fields")


# ── 5. CustomSourceScraper (origin + parser hand-off, no LLM) ─────────────────

def test_custom_scraper_origin_and_handoff():
    from scraping.custom_source_scraper import CustomSourceScraper

    captured = {}

    class _StubParser:
        async def parse(self, source, html, **kwargs):
            captured["source"] = source
            captured["html"] = html
            captured["kwargs"] = kwargs
            return []

        async def close(self):
            captured["closed"] = True

    scraper = CustomSourceScraper(
        7, "https://site.org/funding/list?p=1", name="My List",
        country="Kazakhstan", parser=_StubParser(),
    )
    assert scraper._origin() == "https://site.org"
    assert scraper.name == "custom:7"

    # Stub out the (SSRF-guarded) network fetch.
    async def _fake_fetch(url, **kw):
        captured["fetched_url"] = url
        return "<html><body>grants</body></html>"

    scraper._guarded_fetch = _fake_fetch  # type: ignore[assignment]

    grants = asyncio.run(scraper.scrape())
    assert grants == []
    assert captured["fetched_url"] == "https://site.org/funding/list?p=1"
    assert captured["source"] == "custom:7"
    assert captured["kwargs"]["base_url"] == "https://site.org"  # origin, not full URL
    assert captured["kwargs"]["default_org"] == "My List"
    assert captured["kwargs"]["default_country"] == "Kazakhstan"
    # A caller-supplied (shared) parser must NOT be closed by the scraper.
    assert "closed" not in captured
    print("OK CustomSourceScraper derives origin + hands HTML to parser")


# ── 6. URL guard (SSRF) — offline, IP literals only ──────────────────────────

def test_url_guard_blocks_private_and_allows_public():
    from core.url_guard import assert_public_url, UnsafeURLError

    blocked = [
        "http://127.0.0.1/x",            # loopback
        "http://10.0.0.5/x",             # RFC1918
        "http://192.168.1.1/x",          # RFC1918
        "http://169.254.169.254/latest", # cloud metadata (link-local)
        "http://[::1]/x",                # IPv6 loopback
        "ftp://93.184.216.34/x",         # bad scheme
        "https://0.0.0.0/x",             # unspecified
    ]
    for url in blocked:
        try:
            asyncio.run(assert_public_url(url))
        except UnsafeURLError:
            continue
        raise AssertionError(f"expected UnsafeURLError for {url}")

    # A public IP literal must pass without hitting the network (no DNS).
    asyncio.run(assert_public_url("http://93.184.216.34/grants"))

    # CGNAT 100.64/10 is not globally routable -> must be blocked (is_global).
    try:
        asyncio.run(assert_public_url("http://100.64.0.1/x"))
    except UnsafeURLError:
        pass
    else:
        raise AssertionError("expected CGNAT 100.64/10 to be blocked")
    print("OK url_guard blocks private/reserved/CGNAT + allows public")


def test_url_guard_rejects_mixed_dns_records():
    """If a hostname resolves to BOTH a public and a private address, refuse it
    (defends against multi-record / rebinding-style answers)."""
    import core.url_guard as guard
    from core.url_guard import assert_public_url, UnsafeURLError

    def _fake_getaddrinfo(host, *a, **k):
        # One public, one private record for the same name.
        return [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("10.0.0.7", 0)),
        ]

    orig = guard.socket.getaddrinfo
    guard.socket.getaddrinfo = _fake_getaddrinfo
    try:
        try:
            asyncio.run(assert_public_url("http://mixed.example/x"))
        except UnsafeURLError:
            pass
        else:
            raise AssertionError("expected mixed public/private DNS to be blocked")
    finally:
        guard.socket.getaddrinfo = orig
    print("OK url_guard rejects mixed public/private DNS records")


def test_guarded_fetch_blocks_redirect_to_private():
    """_guarded_fetch must validate EACH hop: a redirect from a public URL to a
    private address is refused before the second request is issued."""
    import scraping.custom_source_scraper as css
    from scraping.custom_source_scraper import CustomSourceScraper
    from core.url_guard import UnsafeURLError

    class _Resp:
        is_redirect = True

        def __init__(self, location):
            self.next_request = SimpleNamespace(url=location)

        def raise_for_status(self):  # pragma: no cover - not reached
            pass

    class _FakeClient:
        def __init__(self, *a, **k):
            self.gets = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            self.gets += 1
            # First (and only) response redirects a PUBLIC url to loopback.
            return _Resp("http://127.0.0.1/secret")

    orig = css.httpx
    css.httpx = SimpleNamespace(AsyncClient=lambda *a, **k: _FakeClient())
    try:
        scraper = CustomSourceScraper(1, "https://good.example/list")
        # Skip DNS for the first hop by validating an explicit public IP literal.
        try:
            asyncio.run(scraper._guarded_fetch("http://93.184.216.34/list"))
        except UnsafeURLError:
            pass
        else:
            raise AssertionError("expected redirect-to-private to be blocked")
    finally:
        css.httpx = orig
    print("OK _guarded_fetch blocks redirect to a private address")


# ── 7. Runner runtime path (fake DB + stubbed scraper) ───────────────────────

def test_run_custom_sources_runtime():
    """Exercise the real run_custom_sources_async control flow with a fake DB and
    stubbed scraper — proves the AdaptiveParser import resolves, grants are saved,
    and a per-source failure is isolated (rollback + error status, no crash)."""
    import types as _types
    import scraping.runner as r
    from models.custom_source import CustomSource

    sources = [
        CustomSource(id=1, url="https://good.io/g", name="Good", enabled=True),
        CustomSource(id=2, url="https://bad.io/g", name="Bad", enabled=True),
    ]

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            inner = self._rows

            class _S:
                def all(self_inner):
                    return inner
            return _S()

    class _FakeSession:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, stmt):
            # First call (the SELECT) returns the source rows; UPDATEs return None.
            from sqlalchemy.sql import Select
            if isinstance(stmt, Select):
                return _Result(sources)
            return None

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    # Stub the scraper: source #2 raises to drive the rollback/error branch.
    class _StubScraper:
        def __init__(self, sid, url, **kw):
            self.sid = sid

        async def scrape(self):
            if self.sid == 2:
                raise RuntimeError("boom")
            from scraping.base_scraper import GrantData
            return [GrantData(title="G", source_url="https://good.io/grant/1")]

    class _StubParser:
        async def close(self):
            pass

    async def _fake_bulk_save(db, grants):
        return (len(grants), 0)

    orig = (r.CustomSourceScraper, r.AdaptiveParser, r.bulk_save_grants)
    r.CustomSourceScraper = _StubScraper
    r.AdaptiveParser = lambda *a, **k: _StubParser()
    r.bulk_save_grants = _fake_bulk_save
    try:
        db = _FakeSession()
        summary = asyncio.run(r.run_custom_sources_async(db))
    finally:
        r.CustomSourceScraper, r.AdaptiveParser, r.bulk_save_grants = orig

    assert summary["new"] == 1, summary
    assert summary["total"] == 1, summary
    assert summary["errors"] == 1, summary
    assert db.rollbacks == 1  # only the failing source rolled back
    by = summary["by_source"]
    assert by["Good"]["new"] == 1 and by["Bad"]["errors"] == 1
    print("OK run_custom_sources_async saves, isolates failures, updates status")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} Phase-7 offline tests passed.")


if __name__ == "__main__":
    _run_all()
