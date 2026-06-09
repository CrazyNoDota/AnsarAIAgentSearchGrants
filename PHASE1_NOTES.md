# Phase 1 — Reliable grant search (stealth scraping) · Implementation Notes

Status: IMPLEMENTED (offline-verified; live scraping + camoufox launch need the VPS)
Date: 2026-06-08

This phase makes grant search reliable for bot-walled portals by adding a stealth
browser layer, a sequential Redis queue, an adaptive LLM parser loop, reviving the
dead sources (EU Funding, UNDP, UKRI, GCF), and adding structured filter fields.
All additions are **additive** and do not change the behavior of the 34 working
light scrapers.

---

## 1. What was added

### Stealth browser worker — `backend/scraping/stealth_browser.py`
- Renders pages through **camoufox** (anti-detect Firefox) via Playwright's async API.
- **One browser at a time**: a module-level `asyncio.Lock` serializes launches.
- **No resident browsers**: the browser is launched per `fetch_html()` call and torn
  down in a `finally` before returning (RAM budget: 0.5–1.5 GB/session on a 4 GB VPS).
- **Graceful degradation**: if `camoufox` isn't importable, or the patched Firefox
  binary isn't fetched, it raises `StealthUnavailable` instead of crashing. On the VPS,
  run `pip install camoufox[geoip]` then `python -m camoufox fetch` to activate the
  real launch path. `stealth_available()` is a cheap pre-check.

### Base-scraper integration — `backend/scraping/base_scraper.py`
- New `BaseScraper.fetch(url, stealth=…)`: a scraper opts into stealth per-call or
  wholesale via `stealth_default`. If stealth is unavailable and
  `allow_http_fallback` is True, it transparently falls back to plain `httpx`.
- **Broadened stealth fallback** (review fix #5): the fetch now falls back to the cheap
  HTTP path not only on `StealthUnavailable` but also on **real stealth runtime errors**
  (navigation timeout, page/browser crash, camoufox/Playwright runtime error) — a stealth
  glitch degrades to HTTP instead of yielding nothing. `KeyboardInterrupt`/`SystemExit`/
  `MemoryError` are re-raised, and runtime errors are logged with context + traceback so
  genuine bugs stay visible.
- `GrantData` gained optional structured fields: `budget_min/max`, `currency`,
  `region`, `industry`, `grant_amount`.

### NIM client — `backend/scraping/nim_client.py`
- Thin wrapper over `openai.AsyncOpenAI` pointed at **NVIDIA NIM Chat Completions**
  (`settings.nvidia_base_url` + `nvidia_model`), reusing the exact pattern already in
  `ai_search_agent.py` / `services/ai_service.py`. Keys come from settings/.env — never
  hardcoded. Generous 120 s timeout (480B first-token latency from Phase 0).

### Adaptive LLM parser loop — `backend/scraping/adaptive_parser.py` + `parser_cache.py`
- Loop: **LLM reads page → writes a reusable CSS-selector strategy (JSON) → strategy
  cached per source → later runs apply the strategy with BeautifulSoup, no LLM call.**
- If the cached strategy yields nothing (page drifted), the stale strategy is
  **invalidated (deleted) BEFORE re-learning** (review fix #3) via the new
  `ParserCache.invalidate(source)` — so the dead cache path + LLM call isn't repeated on
  every later run. A **newly-learned strategy is cached only if it extracts >0 grants**,
  and a `MAX_RELEARN_ATTEMPTS` guard bounds the LLM re-learn loop. Final fallback is
  direct LLM extraction of grants from page text.
- The strategy prompt + direct-extraction prompt now also pull **amount / region /
  industry** (review fix #4) and `apply_strategy()` maps them into `GrantData`,
  normalizing the free-text amount via `parse_budget()` into `budget_min/max/currency`.
- `ParserCache` is **Redis-backed** (`settings.redis_url`) with a **JSON-file fallback**
  (`backend/scraping/_parser_cache/`, git-ignored) so it works offline / in tests.
  TTL 30 days.

### Sequential scrape queue — `backend/scraping/scrape_queue.py`
- Heavy/browser scrapes run through a **Redis list, popped one at a time** — never
  `asyncio.gather` over all heavy sources. Degrades to an in-process sequential loop if
  Redis is down (queue semantics preserved). One job crashing never kills the queue.
- **GLOBAL (cross-process) guarantee** (review fix #2): before draining, `process()`
  acquires a **Redis distributed lock** (`SET key token NX PX 30min`) with a unique
  token, released via a **compare-and-delete Lua script** so a slow worker can't delete
  a lock another worker re-acquired after TTL expiry. The lock auto-expires (lease), so
  a crashed worker never deadlocks the queue. If another processor already holds the
  lock, `process()` returns immediately (its jobs stay queued for the active holder).
  A module-level `asyncio.Lock` is kept as a **secondary in-process guard**. If Redis is
  absent, it falls back to the in-process lock only and **logs that the cross-process
  guarantee is DEGRADED**.

### Budget parser — `backend/scraping/budget_parser.py`
- Pure-python `parse_budget()` normalizes free-text amounts (`"Up to $50,000"`,
  `"€100K-€500K"`, `"GBP 2 million"`) into `(budget_min, budget_max, currency)`.
  Used by the runner to populate the new structured columns from `grant_amount`.

---

## 2. How the stealth path works (end to end)

1. The runner splits scrapers into **light** (API/RSS over HTTP → `asyncio.gather`) and
   **heavy** (`HEAVY_SOURCES = eu_funding, undp_grants, innovate_uk, gcf_grants`).
2. Heavy sources are enqueued on the Redis queue and processed **one at a time**.
3. Each heavy scraper first tries its cheap fast path (API/RSS). If that returns 0, it
   calls `self.fetch(url, stealth=True)` → camoufox renders the page → `AdaptiveParser`
   extracts grants (cached strategy if available, else LLM-learns one).
4. Results flow into the existing `bulk_save_grants`, which **dedups by `source_url`**
   (unchanged) and now also fills `budget_*`, `currency`, `region`, `industry`.

---

## 3. Revived dead sources

| Source | Module | Revival approach |
|--------|--------|------------------|
| EU Funding & Tenders | `scraping/eu_funding.py` | SEDIA API fast path; on 0 → stealth-render the open-calls page + adaptive parser. Tags `region="Europe"`. |
| UNDP | `scraping/undp_grants.py` | RSS fast path; on 0 → stealth-render the procurement listing + adaptive parser. |
| UKRI / Innovate UK | `scraping/innovate_uk.py` | Existing API + Atom feed; on 0 → stealth-render `ukri.org/opportunity/` + adaptive parser. Tags `region="United Kingdom"`. |
| GCF (Green Climate Fund) | `scraping/gcf_grants.py` **(new)** | Best-effort JSON API; on 0 → stealth-render the RFP page + adaptive parser. Tags `region="Global"`, `industry="Climate / Green Energy"`. Registered in the runner. |

Dedup by `source_url` is consistent with existing behavior (handled centrally in
`bulk_save_grants`).

---

## 4. Filter fields added

- **Model** (`models/grant.py`): `budget_min`, `budget_max` (`Numeric(18,2)`), `currency`
  (`String(8)`), `region` (`String(128)`). `deadline` (Date) and `industry` already
  existed. Migration **`004_phase1_filters.py`** (Alembic, `down_revision=003_rag_learning`)
  adds these columns + **only NEW Phase-1-owned indexes**: `ix_grants_region`,
  `ix_grants_budget_max`, `ix_grants_industry`.
- **Migration fixed** (review fix #1): 004 no longer (re)creates `ix_grants_deadline` —
  that index is **owned by 001** (`001_initial.py` creates it). Re-creating it broke a
  clean `001→002→003→004` upgrade, and the old downgrade wrongly dropped the pre-existing
  (non-Phase-1) deadline index. 004's upgrade adds only Phase-1 columns/indexes and its
  downgrade drops only those — `ix_grants_deadline` and the `deadline` column are left
  untouched. Chain verified linear: `001_initial → 002_notif_sub → 003_rag_learning →
  004_phase1_filters`.
- **Schema** (`schemas/grant.py`): the four new fields added to `GrantBase` and
  `GrantResponse`.
- **Query path** (`services/grant_service.list_grants`): new filters `region`, `industry`,
  `deadline_before`, `deadline_after`, `budget_min`, `budget_max` (budget uses range
  overlap). Exposed as query params on `GET /grants` (`api/routes/grants.py`).

---

## 5. Verified vs. needs-VPS

**Verified offline (no network / no LLM / no browser / no real Redis):**
`backend/scraping/tests/test_phase1.py` (**11 tests**, all pass via `python -m pytest`
and standalone):
- All new modules import cleanly even with camoufox/playwright absent.
- `apply_strategy()` extracts 3 grants from a saved HTML fixture (cached-parser path,
  no LLM) — relative-URL absolutization, deadline parsing, org mapping all checked.
- Adaptive loop with a **stub NIM**: first call learns + caches a strategy (LLM called
  once), second call is served from cache (LLM called **zero** times).
- `parse_budget()` cases.
- `ScrapeQueue` processes jobs **strictly one-at-a-time** in FIFO order (asserted by
  interleaving check), using the in-process fallback (no Redis needed).
- **(fix #3)** A stale cached strategy returning 0 is invalidated and re-learned; a
  newly-learned strategy that extracts 0 is **NOT** cached.
- **(fix #5)** When the stealth path raises a runtime browser error, `fetch()` falls
  back to the HTTP path (sentinel body returned, not empty).
- **(fix #2)** Two overlapping `ScrapeQueue.process()` loops sharing one (fake) Redis
  serialize via the distributed lock — max concurrency 1, all jobs drained exactly once,
  lock released (compare-and-del, not left dangling).
- **(fix #4)** Budget/region/industry are populated into `GrantData` from a fixture via
  the adaptive parser (`grant_amount="Up to $500,000"` → `budget_max=500000.0,
  currency="USD"`; `region="Global"`; `industry="Climate / Green Energy"`).
- **(fix #1)** Static AST check: migration 004's upgrade does not reference
  `ix_grants_deadline` and its downgrade drops only the three Phase-1 indexes.

The fake-Redis lock test asserts the **acquire/release contract** (SET NX PX + Lua
compare-and-del); a real Redis is still only exercised on the VPS.

Also verified: every touched module imports (`models.grant` import confirms the new
SQLAlchemy columns are valid), the runner registers GCF (38 scrapers total) and splits
4 heavy / 34 light, and `GET /grants` exposes the new filter params.

**Needs the VPS / live env (could not verify here):**
- Real camoufox launch — patched Firefox not fetched in this env
  (`stealth_available()` → False here). Run `python -m camoufox fetch` on the VPS.
- Live scraping of EU/UNDP/UKRI/GCF behind their real bot walls.
- Live NIM strategy generation (key works per Phase 0; not re-billed here).
- Running migration `004` against the real Postgres (Alembic chain validated statically
  incl. an AST check that 004 leaves `ix_grants_deadline` alone; `down_revision` points at
  the current head `003_rag_learning`).
- The Redis distributed processor lock against a **real** Redis (the acquire/release
  contract is unit-tested with a fake Redis; a live `SET NX PX` + Lua eval still needs the
  VPS Redis).
- Redis-backed queue/cache against a real Redis (file/in-process fallbacks were tested).

---

## 6. Blockers / risks

1. **camoufox Firefox binary** must be fetched on the VPS (`python -m camoufox fetch`,
   several hundred MB) before any stealth fetch succeeds. Until then, heavy scrapers fall
   back to their HTTP fast path only (same as today).
2. **Webwright→NIM is NOT used** and remains unproven (Phase 0 blocker #5: Webwright speaks
   the OpenAI *Responses* API, NIM is *Chat Completions* only). The adaptive loop calls NIM
   Chat Completions **directly** via the repo's existing `openai` client. No Webwright→NIM
   integration is claimed.
3. **Selector drift**: LLM-generated strategies can break when portals redesign. Mitigated
   by **invalidating + auto-re-learning** when a cached strategy yields 0 (the stale entry
   is deleted, not just re-overwritten), a `MAX_RELEARN_ATTEMPTS` guard against infinite
   LLM loops, only caching strategies that extract >0 grants, plus a 30-day TTL.
4. **RAM on the 4 GB VPS**: heavy scrapers are serialized (queue + global launch lock + per-
   task teardown), but if other services spike, consider a `mem_limit` on the worker
   container and/or a smaller/faster NIM model for the parser-generation calls.
5. **Real captcha walls**: handled only by camoufox stealth (solvecaptcha dropped). If a
   hard captcha wall appears, free alternatives must be revisited (per the plan).

---

## 7. Files touched

New:
- `backend/scraping/stealth_browser.py`
- `backend/scraping/nim_client.py`
- `backend/scraping/parser_cache.py`
- `backend/scraping/adaptive_parser.py`
- `backend/scraping/scrape_queue.py`
- `backend/scraping/budget_parser.py`
- `backend/scraping/gcf_grants.py`
- `backend/database/migrations/versions/004_phase1_filters.py`
- `backend/scraping/tests/__init__.py`, `test_phase1.py`, `fixtures/sample_grants_list.html`
- `PHASE1_NOTES.md`

Modified (additive):
- `backend/scraping/base_scraper.py` (stealth `fetch`, GrantData fields)
- `backend/scraping/eu_funding.py`, `undp_grants.py`, `innovate_uk.py` (stealth+adaptive fallback)
- `backend/scraping/runner.py` (GCF registered, heavy/light split via queue, structured fields in save)
- `backend/models/grant.py`, `backend/schemas/grant.py` (filter fields)
- `backend/services/grant_service.py`, `backend/api/routes/grants.py` (filter query path)
- `backend/requirements.txt` (`camoufox[geoip]`)
- `.gitignore` (parser cache dir)
