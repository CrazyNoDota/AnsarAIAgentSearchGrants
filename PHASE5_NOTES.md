# Phase 5 — AI consultant & knowledge base · Notes

Status: implemented + offline-verified · codex gate **8/10** · 2026-06-09
Repo: `AnsarAIAgentSearchGrants` (additive; existing tables/endpoints untouched)
Execution: **sub-agent implemented**, then **codex review gate** — codex fixed its
own findings across two write-mode rounds (owner's loop).

Implements the Phase 5 plan items: an **AI consultant** (grounded Q&A on grant
terms + improvement recommendations + completeness/fit check of a document set
against the grant's requirements) and a **knowledge base** (past applications,
successful cases, reusable templates, submission history/results) used to ground
the consultant's advice in the user's own prior work.

## What was added

**Knowledge base model** — `backend/models/knowledge_entry.py`
- One flexible, USER-SCOPED table `knowledge_entries` holds all four kinds:
  `past_application | successful_case | template | submission`. NOT NULL
  `user_id` FK → users (CASCADE); optional `package_id` FK → application_packages
  and `grant_id` FK → grants (both SET NULL so an entry survives source deletion).
  Columns: `kind`, `title`, `content`, `outcome`, `funder`, `meta` (JSON bag,
  server_default `{}`), `embedding_status`. `search_text()` builds the
  deterministic text used for embedding + keyword search.

**Knowledge service** — `backend/services/knowledge_service.py`
- Fully USER-SCOPED CRUD (`create`/`get_owned`/`list_for_user`/`update`/`delete`)
  — no unscoped getter. `validate_kind`/`validate_outcome` are pure.
- Semantic indexing (`index_entry(entry, user_id)`) reuses the existing
  `EmbeddingService` (NVIDIA NIM) + pgvector, mirroring `grant_embeddings`. The
  embedding delete/insert SQL is itself **user-scoped** (joins/guards on
  `user_id`) and wrapped in `begin_nested` + try/except so an embedding/DB
  failure is best-effort and **never aborts the entry write**. `update()` marks
  the embedding stale (`pending`) when ANY search-text field changes
  (content/title/kind/funder/outcome) and coerces `content=None` → `""`.
- Retrieval is USER-SCOPED end-to-end: `semantic_search` filters by `user_id`
  **inside the SQL** (a vector hit can never surface another user's entry);
  `keyword_search` is the deterministic ILIKE fallback (also user-scoped);
  `retrieve_context` prefers semantic, falls back to keyword.

**AI consultant service** — `backend/services/consultant_service.py`
- LLM via **NVIDIA NIM Chat Completions DIRECT** (`settings.nvidia_*`). Strict
  anti-hallucination `CONSULTANT_SYSTEM_PROMPT` (answer ONLY from grounded
  context; never invent; explicit "not found in the provided data"; attribute
  sources; do not change computed numbers).
- Pure, testable context builders: `build_grant_context` (reused from Phase 3),
  `build_package_context`, `build_kb_context`, `_build_grounded_context` (labels
  every source block).
- `ask(...)` — grounded Q&A over grant + optional owned package + user's KB
  cases. Deterministic fallback when the LLM is unavailable returns the verified
  context (never fabricates); explicit not-found when no context exists.
- `assess_completeness(...)` + `build_recommendations(...)` — **deterministic,
  pure** completeness/fit check reusing Phase-4 `calendar_service.evaluate_sections`
  (drafted/TODO/missing) + Phase-2 fit breakdown (eligibility gaps). Flags
  missing/TODO/weak sections, absent **required** sections, eligibility gaps,
  percent/stage.
- `review_package(...)` — returns the deterministic `assessment` +
  `recommendations` (always authoritative) and an optional LLM-phrased
  `summary`. **Grounding guards:** the LLM summary is discarded (→ deterministic
  fallback, `llm_used=False`) if it (a) states a percentage that differs from the
  computed values, or (b) makes a readiness/completeness claim that contradicts
  the deterministic assessment.

**Schemas** — `backend/schemas/knowledge.py`, `backend/schemas/consultant.py`.

**Routes**
- `backend/api/routes/knowledge.py` — `POST/GET/PATCH/DELETE /knowledge`,
  `GET /knowledge/{id}`, `GET /knowledge/search`. All AUTH + user-scoped; create
  verifies a supplied `package_id` is owned (no cross-user FK link / ID oracle);
  create/update best-effort index via the user-scoped `index_entry`.
- `backend/api/routes/consultant.py` — `POST /consultant/ask` (grounds in grant
  + owned package + user KB), `POST /consultant/review` (owned package; pulls
  deterministic Phase-2 fit when profile+grant still exist; required keys from
  the Phase-3 default section templates). Every package read goes through
  `DocumentService.get_owned(id, user_id)`.

**Migration** — `backend/database/migrations/versions/009_phase5_knowledge_base.py`
- `down_revision = '008_phase4_email_channel'`. Creates ONLY two new tables:
  `knowledge_entries` (+ user_id/kind indexes) and `knowledge_embeddings` (with a
  real `vector(1024)` column created via raw SQL, an `ivfflat`
  `vector_cosine_ops` index, and an `entry_id` index). The `vector` extension is
  assumed already present (from the initial migration) — NOT created/dropped.
  **Additive + reversible** (AST-tested): downgrade drops only the two tables +
  their indexes. No new dependency.

**Registration** — `backend/main.py` (both routers) + `backend/models/__init__.py`
(`KnowledgeEntry` exported). No new config (Phase 5 reuses `nvidia_*` LLM +
embeddings already in `core/config.py` / `.env.example`). No new pip deps.

## Verified OFFLINE (no live network / LLM / DB)
`backend/tests/test_phase5.py` — **23 checks, all green**
(`../.venv/Scripts/python.exe tests/test_phase5.py`; same standalone style as
test_phase2/3/4: `SimpleNamespace` stubs, stubbed-LLM client, AST migration
hygiene). Covers: pure context builders + source labeling; anti-hallucination
(strict system prompt; no-context → explicit not-found; no-LLM → grounded
context, no fabrication); stubbed-LLM grounded answer; **deterministic review
numbers + percentage guard + readiness-claim guard** (a wrong % or a false
"ready to submit" is discarded → deterministic fallback); completeness
classification (missing/TODO/weak/absent/eligibility-gaps); deterministic
recommendations; knowledge kind/outcome validation; **user-scoping** of KB
retrieval + CRUD + indexing (incl. `user_id` in the vector SQL, no unscoped
getter); create-route package-ownership check; keyword fallback shaping;
`content=None` coercion; consultant/knowledge routes read user-scoped only;
model user-scoped + columns; routers/model registered; migration 009 additive +
reversible with the pgvector column/index. App boots with all 8 new routes
(`/knowledge*`, `/consultant/ask`, `/consultant/review`) — `import main` OK.

## Review gate (codex) — final SCORE 8/10
codex `exec` (gpt-5.5), three rounds:
- **Round 1 (read-only) = 6/10.** Findings: [High] LLM review summary could
  override deterministic numbers; [High] create accepted `package_id` without an
  ownership check (cross-user FK link / ID oracle); [Med] `index_entry` not
  user-scoped + could roll back the write; [Med] embedding stale only on content
  change; [Low] no ivfflat vector index; [Low] `meta` no server default.
- **Round 2: codex self-fixed all six** (write mode), then read-only re-review
  = **8/10**. Confirmed all six fixed. Two NEW [Med]: PATCH `{content:null}` →
  500 on the NOT NULL column; the review guard only checked percentages (a
  correct % with a false qualitative readiness claim slipped through).
- **Round 3: codex self-fixed both** (write mode): `update()` coerces
  `content=None` → `""`; added a deny-list readiness-claim guard. Final
  confirming read-only re-review = **8/10**.

**Residual (non-blocking, [Med] observation):** the readiness-claim guard is
deny-list based, so an exotic paraphrase ("submission-ready", "all required
sections are done") could still pass the *phrasing* check. This is defense in
depth only — the **authoritative numbers always live in the deterministic
`assessment`** returned to the client, and the percentage guard still fires. A
future hardening could always use the deterministic summary or expand the list.

## Needs the live VPS / DB / NIM (not exercised here)
- Applying migration 009 against real Postgres (incl. the `ivfflat` index; needs
  the `vector` extension already enabled, as for grant_embeddings).
- Live NVIDIA NIM embedding of knowledge entries + live pgvector similarity for
  `/knowledge/search` and consultant KB grounding.
- Live NIM Chat Completions for `/consultant/ask` answers + `/consultant/review`
  narrative (deterministic paths verified offline; LLM phrasing needs the key).

## Risks / follow-ups
- Readiness-claim guard paraphrase gap (above) — non-blocking.
- `index_entry` runs inline in the create/update request (best-effort, bounded);
  a high-volume KB could move indexing to a background job later.
- No `ivfflat` index tuning yet (lists=100 default); fine for current scale.
