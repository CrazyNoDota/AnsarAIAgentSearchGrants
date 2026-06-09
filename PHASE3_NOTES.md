# Phase 3 — Application document package generation · Notes

Status: implemented + offline-verified · 2026-06-09
Repo: `AnsarAIAgentSearchGrants` (additive; existing tables/endpoints untouched)

Implements the Phase 3 plan item: generate a structured grant-application
**document package** (Executive Summary, Project Description, Objectives & KPIs,
Budget, + Team and Sustainability) for a (company profile, grant) pair, draft
each section with the LLM, read scanned/PDF grant calls with a **multimodal**
model, and **export** to .docx / .pdf / .md.

## What was added

**Templates** — `backend/services/document_templates.py`
- `SectionTemplate` dataclass + `DEFAULT_SECTIONS` registry (the four plan
  sections plus Team and Sustainability), each with `key/title/order/guidance/
  max_tokens`. `get_sections(keys)` selects/validates/orders (unknown key →
  `ValueError`, de-dupes, canonical order).

**Generation** — `backend/services/document_service.py`
- `DocumentService` drafts each section via **NVIDIA NIM (Qwen3) Chat
  Completions DIRECT** (same path as `ai_service`/`nim_client`; NOT Webwright's
  Responses API — Phase 0 finding).
- **Anti-hallucination** (consistent with RAG/matching): a strict system prompt
  forbids inventing facts; sections are grounded ONLY in the company profile +
  grant details (+ optional extracted grant-call text); unknowns must be emitted
  as `[TODO: ...]` placeholders. Context is built by **pure functions**
  (`build_profile_context` reuses `profile.profile_text()`, `build_grant_context`)
  so prompts are unit-testable with no network.
- **Graceful degradation:** no LLM (or any per-section error) → a deterministic
  scaffold with the section intent + a TODO (package still well-formed, never
  raises). Generation is sequential; per-section timeout 60s.
- **Persistence is fully USER-SCOPED from the start** (Phase 2 lesson):
  `create_package`, `get_owned`, `list_for_user`, `update_sections`, `delete`
  all take/enforce `user_id`; there is no unscoped getter.

**Multimodal reader** — `backend/services/multimodal_service.py`
- `MultimodalService` calls **StepFun `step-3.7-flash`** (vision) via Chat
  Completions with `image_url` base64 **data-URLs** (png/jpg/jpeg/webp) for
  OCR-style reading of grant-call PDFs/scans/screenshots.
- PDFs are rasterized page-by-page (first 8 pages, ~144dpi) with **PyMuPDF**
  (`fitz`), imported lazily — missing dep raises a clear `RuntimeError`, never an
  `ImportError` leak. `build_messages` is pure/testable. Returns `None` (not an
  error) when the model isn't configured. New config: `nvidia_step_*`
  (key falls back to `nvidia_api_key`; `step_api_key`/`use_step` properties).

**Export** — `backend/services/export_service.py`
- One document model (`{title, sections:[{title,content}]}`) → `to_markdown`
  (pure-python, always available), `to_docx` (python-docx), `to_pdf` (reportlab,
  pure-python; XML-escaped). `render(pkg, fmt)` dispatches; unknown fmt →
  `ValueError`; missing optional dep → `RuntimeError` (surfaced as HTTP 501).

**Model / schema / API**
- `backend/models/application_document.py` — `ApplicationPackage` (user_id FK
  CASCADE NOT NULL; profile_id/grant_id FK **SET NULL** so packages survive
  source deletion; denormalized `grant_title`; `sections` JSON; status).
- `backend/schemas/application.py` — `GenerateRequest`, `ApplicationResponse`,
  `ApplicationUpdate`, `ExtractResponse`.
- `backend/api/routes/applications.py` — `POST /generate`, `GET /` (paged,
  scoped), `GET /{id}`, `PATCH /{id}` (edit sections), `DELETE /{id}`,
  `GET /{id}/export?format=`, `POST /extract` (upload PDF/image → OCR text;
  10 MB cap). Registered in `main.py`; `ApplicationPackage` exported from
  `models/__init__.py`; health adds a `multimodal` flag.

**Migration** — `backend/database/migrations/versions/007_phase3_applications.py`
- `revision='007_phase3_applications'`, `down_revision='006_profile_user_scope'`
  (chain 001→…→006→007). Creates ONLY `application_packages` (+ user_id index);
  `downgrade()` drops only that. Additive + reversible (AST-tested).

**Dependencies** — `backend/requirements.txt`: `python-docx`, `reportlab`,
`pymupdf`. `.env.example` documents `NVIDIA_STEP_*`.

## Verified OFFLINE (no live network / LLM / multimodal / pgvector / real DB)
`backend/tests/test_phase3.py` — **13 checks, all green** (`python
tests/test_phase3.py`, also importable under pytest):
1. Template registry well-formed; `get_sections` selects/validates/orders/dedupes.
2. Context building deterministic + omits missing fields (no invention).
3. Section messages embed the anti-hallucination system prompt; extracted-call
   text truncated to 4000 chars; no header when absent.
4. No-LLM generation → deterministic TODO scaffolds, all sections in order.
5. Stub-LLM generation stores model output verbatim; unknown key → ValueError.
6. Per-section LLM error falls back to a scaffold (does not raise).
7. Export: markdown deterministic; format dispatch validated; docx/pdf render to
   bytes when deps present, else clear RuntimeError. Filename slugged safely.
8. Multimodal: data-URL encoding + bad-mime rejection; message shape
   (text + N image_url parts); PDF path guarded behind PyMuPDF.
9. Application packages user-scoped (no unscoped getter; every accessor takes
   user_id). Model/schema/route consistent.
10. Migration 007 additive + reversible.

Additionally exercised live-locally (deps installed into `.venv`): real .docx
(36 KB) and .pdf (1.8 KB) rendering; PDF→PNG data-URL rasterization via PyMuPDF;
full `main.app` boot with all 5 `/applications` routes registered. Deps added to
the test venv: python-multipart, python-docx, reportlab, pymupdf, openai.

## Review hardening (codex round 1, 7/10 → addressed)
- **[Med] Unbounded upload read:** `/extract` now reads at most
  `MAX_UPLOAD_BYTES + 1` (`file.read(limit+1)`) so an oversized body is rejected
  (413) without being fully buffered.
- **[Med] PDF pixel blow-up:** `pdf_bytes_to_image_data_urls` clamps per-page
  render zoom so neither rendered side exceeds `MAX_RENDER_DIM_PX` (2200px),
  bounding the bitmap allocation regardless of declared page size.
- **[Med] Corrupt-PDF error class:** unreadable/non-PDF uploads now raise
  `ValueError` (→ HTTP 400); `RuntimeError` is reserved strictly for "PyMuPDF
  missing" (→ 501). Both `fitz.open` and rasterization are wrapped.
- **[Low] Section bounds:** `ApplicationSection.content` ≤ 50k chars, section
  lists (`GenerateRequest.sections`, `ApplicationUpdate.sections`) ≤ 50 items.
- **[Low] Accurate `pages_or_images`:** `extract_from_upload` now returns
  `(text, n)` and the API reports the real page/image count, not a constant 1.
- Tests: added corrupt-PDF (ValueError) + `extract_from_upload` page-count
  checks (now **15 offline checks**).

## Review hardening (codex round 2, 8/10 — confirmation)
- **[High] Render cap could be defeated:** the per-page `zoom = max(zoom, 0.1)`
  floor could raise a safe sub-floor zoom back up for a tiny PDF declaring a
  huge MediaBox, re-introducing a large allocation. Fixed: the floor is removed;
  zoom is only ever clamped *down* to honour `MAX_RENDER_DIM_PX`, and a
  degenerate (≤0) page box is skipped. **Verified live:** a 100000×100000pt page
  now renders at exactly 2200×2200px (was ~10000px under the old floor).
- **[Med, residual/accepted] Body limit before multipart parsing:** the
  `file.read(limit+1)` bound prevents the app from fully buffering an oversized
  file, but Starlette has already parsed/spooled the multipart body by the time
  the handler runs. A complete defense belongs at the edge (Caddy/proxy or an
  ASGI body-limit layer) — folded into **Phase 6** (Caddy + hardening) rather
  than adding app-wide middleware now. codex final score: **8/10**.

## Needs the live VPS / DB / NIM / StepFun (not exercised here)
- Applying migration 007 against real Postgres.
- Live NIM section drafting + live StepFun OCR of real grant-call PDFs/scans.
- Real DB persistence of packages and the export download flow end-to-end.

## Risks / follow-ups
- Generation is sequential per section → wall-clock ≈ Σ sections; fine for a
  background/manual call, but consider concurrency or a job/status row if it
  becomes user-facing-synchronous.
- The anti-hallucination guard is prompt-level (system prompt + grounded
  context + TODO placeholders); unlike the matching score there is no numeric
  invariant to assert post-hoc. A future check could flag sections lacking
  any provided fact, or diff named entities against the inputs.
- StepFun reads only the first 8 PDF pages per call (latency/cost bound); long
  calls need pagination/chunking.
- `sections` uses `sa.JSON` (portable). On Postgres consider JSONB if querying
  inside sections becomes necessary.
