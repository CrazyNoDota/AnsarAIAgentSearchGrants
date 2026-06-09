# Phase 2 — User-profile fit analysis · Notes

Status: implemented + offline-verified · 2026-06-09
Repo: `AnsarAIAgentSearchGrants` (additive; existing tables/endpoints untouched)

Implements the Phase 2 plan item: a Company/Project **Profile** entity, a
deterministic+explainable **fit/match engine** (profile ↔ grant), ranked
recommendations, and **RAG semantic matching** over grant text via the existing
pgvector stack.

## What was added

**Model / schema / API**
- `backend/models/profile.py` — `CompanyProfile` (industry, stage, region,
  country, funding_amount_sought, currency, team_size, organization_type,
  keywords, description, past_funding). `profile_text()` builds the NL text used
  for semantic matching.
- `backend/schemas/profile.py` — create/update/read Pydantic schemas (field
  parity with the model, asserted by a test).
- `backend/api/routes/profiles.py` — CRUD + a fit/recommendations endpoint.
  Registered in `backend/main.py` (`app.include_router(profiles.router)`).
- `backend/services/profile_service.py` — persistence/CRUD.
- `backend/models/__init__.py` — exports `CompanyProfile`.

**Matching engine** — `backend/services/matching_service.py`
- **Anti-hallucination design:** the numeric fit score is computed
  DETERMINISTICALLY from comparable features; the LLM (NVIDIA NIM, called
  directly via Chat Completions) is used only to phrase the qualitative
  explanation and never invents/overrides the score. With no LLM the engine
  still returns a score + rule-based strengths/weaknesses.
- **Formula:** weighted average over applicable dimensions
  `fit = Σ(w_d · score_d) / Σ(w_d)`. Only dimensions the profile actually
  provides signal for are counted (a sparse profile isn't penalised for fields
  it never set; the dimension's weight is dropped from the denominator).
- **Dimensions / weights:** industry 0.20, region 0.15, budget 0.20,
  deadline 0.10, stage 0.10, semantic 0.25.
  - industry — **overlap coefficient** (intersection over the smaller token
    vocabulary) of profile industry/keywords vs grant industry/category/title.
    Using the smaller side avoids penalising profiles that list many keywords.
  - region — "Global/International" grants match anyone; otherwise normalized
    whole-phrase equality on region/country (alias-mapped, NOT substring);
    unknown grant geo is neutral (0.6).
  - budget — 1.0 inside `[budget_min, budget_max]`; decays by distance to the
    nearest bound outside it; neutral (0.5) when grant budget is unknown.
  - deadline — open/absent → high; already closed → 0.
  - stage — startup-stage eligibility overlap; unrestricted grant → 0.7.
  - semantic — cosine similarity (clamped to [0,1]) of profile text vs the
    grant's stored embedding via pgvector (`grant_embeddings <=>`). Dropped when
    no embedding/embedding API is available.
- `probability_pct = round(fit·100)` — documented as a **relative** fit
  indicator, not a calibrated statistical probability.
- Strengths/weaknesses are derived from the per-dimension scores (rule-based),
  optionally rephrased by the LLM.

**Migration** — `backend/database/migrations/versions/005_phase2_profiles.py`
- `revision='005_phase2_profiles'`, `down_revision='004_phase1_filters'`
  (linear chain 001→002→003→004→005). Creates only the new `company_profiles`
  table; `downgrade()` drops only that table (additive + reversible — verified
  by an AST test, learning from the Phase 1 migration mistake).

## Review fixes (codex round 1, 6/10 → addressed)
- **Semantic degradation:** the embedding API call is now wrapped — an
  embedding timeout/rate-limit/bad-key drops the semantic dimension instead of
  failing `compute_fit`/`/fit`/`/recommendations`.
- **Region false positives:** geo matching is now whole-phrase equality after
  alias normalization (`_norm_geo`), so "United States" no longer matches
  "United Kingdom", nor "South America" "North America"; US/USA/UK aliases still
  match correctly.
- **Budget currency:** when both sides declare a currency and they differ, the
  raw amounts are treated as not-directly-comparable (neutral 0.5) instead of a
  false perfect fit (FX conversion is a future improvement).
- **Candidate selection:** `/recommendations` now UNIONs RAG hits with a base
  set of recent active grants, so grants without embeddings are still ranked
  (previously RAG-only hid them whenever embeddings were partially populated).
- **LLM grounding:** the explanation is rejected (deterministic fallback used)
  if the model states a percentage different from the computed score. The
  numeric score was already deterministic; this stops contradictory prose.
- **Tests:** added 4 regression tests covering the above (16 checks total).

## Review fixes (codex round 2, 7/10 — security hardening)
- **[High] Profile ownership / data isolation:** profiles had no owner, so any
  authenticated user could read/update/delete/fit any profile. Fixed: added a
  NOT NULL `user_id` FK (`users.id`, ON DELETE CASCADE) to `CompanyProfile`
  (**migration `006_profile_user_scope`**, chain …→005→006); `ProfileService`
  is now fully user-scoped (`create(data, user_id)`, `get_owned`,
  `list_for_user`, `update/delete(..., user_id)`) — the unscoped `get_by_id`
  was removed; all `/profiles` routes (incl. `/recommendations` and `/fit`)
  pass `current_user.id` and 404 on a non-owned profile. `ProfileResponse`
  exposes `user_id`. Two regression tests added (ownership wiring + migration
  006 additive/reversible).
- **[Low] Doc drift:** the region-scoring docstring + notes that still said
  "substring match" were corrected to "normalized whole-phrase equality".

Residual (honest): the explanation guard only catches a contradictory *number*,
not every possible unsupported sentence; `probability_pct` remains an
uncalibrated relative indicator; cross-currency comparison is neutralised, not
converted.

## Verified OFFLINE (no live network / LLM / pgvector / real DB)
`backend/tests/test_phase2.py` — **18 checks, all green** via standalone run
(`python tests/test_phase2.py`) and importable under pytest:
- Each per-dimension scorer (industry/region/budget/deadline/stage) on
  representative inputs, incl. the applicable/not-applicable contract.
- Aggregate formula: a strong fixture scores high (0.875) and a poor fixture
  low (0.227) with a clear separation; inapplicable dimensions leave the
  denominator (sparse profile not penalised).
- Semantic dimension: dropped when embeddings absent; used + clamped to [0,1]
  when present (DB/embedding stubbed — no pgvector needed).
- Strengths/weaknesses shape without the LLM.
- `rank_for_profile` orders best-fit first.
- Model ↔ schema ↔ route field consistency.
- Migration 005 is additive and reversible (only creates/drops `company_profiles`).

Dependencies used by the offline run (installed into `.venv`): pytest,
tenacity, fastapi, pydantic, pydantic-settings, sqlalchemy.

## Needs the live VPS / DB / NIM (not exercised here)
- Applying migration 005 against the real Postgres.
- Real pgvector similarity (the SQL `embedding <=> CAST(:emb AS vector)` query)
  and ensuring grants are embedded at ingest (reuses `embedding_service` /
  `rag_service`; backfill grants without embeddings before relying on the
  semantic dimension).
- Live NIM-generated explanations.

## Risks / follow-ups
- `probability_pct` is a relative indicator, not calibrated — don't present it
  to users as a true success probability without calibration data.
- Semantic dimension silently drops (weight removed) when a grant has no
  embedding; ensure ingest embeds grants so fit isn't computed on structured
  fields alone for new grants.
- Weights (0.20/0.15/0.20/0.10/0.10/0.25) are heuristic; revisit once there is
  outcome data (ties into the existing `learning_service`).
