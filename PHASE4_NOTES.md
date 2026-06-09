# Phase 4 — Deadlines, calendar & notifications · Notes

Status: implemented + offline-verified · 2026-06-09
Repo: `AnsarAIAgentSearchGrants` (additive; existing tables/endpoints untouched)
Execution: **sub-agent implemented**, then **codex review gate** (codex fixed its
own findings) — owner's loop restored to sub-agent-per-phase for Phase 4+.

Implements the Phase 4 plan items: a **calendar** of active grants + an
**application-prep readiness checklist**, and **email notifications** added
ALONGSIDE the existing Telegram channel, triggered by the existing cron/n8n
reminder call.

## What was added

**Calendar + readiness (pure core)** — `backend/services/calendar_service.py`
- Pure, DB-free, unit-testable helpers: `urgency_for`/`days_left_for` (urgency
  buckets identical to the `/deadlines` route), `grant_to_calendar_event`,
  `bucket_by_urgency`.
- **Readiness checklist** over a Phase-3 `ApplicationPackage`'s stored `sections`
  JSON: `evaluate_sections` classifies each section as **drafted / TODO /
  missing** (a `[TODO ...]` / draft-unavailable marker ⇒ not drafted; empty ⇒
  missing), `prep_stage` (`not_started`/`in_progress`/`ready`), and
  `build_readiness` returns per-section status + counts + percent-complete +
  (when the source grant exists) deadline + urgency (`passed` when overdue). All
  pure — the route resolves the package + grant **user-scoped** and passes them in.

**Email channel** — `backend/services/email_service.py`
- SMTP via the Python **stdlib only** (`smtplib`/`email`) — **no new dependency**.
- `build_message` (pure; always a plain-text body, optional HTML alternative),
  `render_deadline_email` (pure; subject + text + HTML for a batch — HTML-escaped,
  links restricted to **http/https** schemes), `EmailService.send_email` /
  `send_bulk`.
- **Degrades gracefully:** `available` is true only when a host AND a sender are
  configured; otherwise logs + returns False/0, never raises (mirrors how the
  Telegram path skips on a missing bot token). Blocking SMTP runs in
  `asyncio.to_thread`. Fan-out bounded by `MAX_RECIPIENTS_PER_SEND = 500`.

**Routes** — `backend/api/routes/deadlines.py` (extended the existing router)
- `GET /deadlines/calendar` — active grants with deadlines, events + urgency
  buckets (auth required).
- `GET /deadlines/readiness` — **USER-SCOPED** readiness for the current user's
  packages, **bounded limit/offset pagination** (`count` + `total` returned).
- `GET /deadlines/readiness/{package_id}` — one **owned** package (404 if not
  owned), via `DocumentService.get_owned(id, user_id)`.
- `GET /deadlines/reminders` — now fans out **Telegram AND email**; each channel
  wrapped so a failure in one never aborts the run; reports per-channel counts.

**Model / config / migration**
- `backend/models/notification_subscription.py` — added `email` (nullable
  VARCHAR(320)) + `email_enabled` (NOT NULL, default true) ALONGSIDE the existing
  Telegram columns. A subscriber gets email only when an address is present AND
  `email_enabled` is true.
- `backend/core/config.py` — `smtp_host/port/user/password`, `smtp_use_tls`
  (STARTTLS/587 default), `smtp_use_ssl` (implicit SSL/465), `email_from`, plus
  `reminder_cron_secret`; properties `email_sender` (falls back to `smtp_user`)
  and `use_email`. All optional with safe empty defaults. `.env.example` documents
  `SMTP_*` / `EMAIL_FROM` / `REMINDER_CRON_SECRET`.
- `backend/database/migrations/versions/008_phase4_email_channel.py` —
  `down_revision='007_phase3_applications'`. Adds ONLY the two
  `notification_subscriptions` columns (`email_enabled` server_default TRUE so a
  non-empty table backfills safely); `downgrade()` drops only those two.
  **Additive + reversible** (AST-tested). No new table.
- `backend/services/document_service.py` — `list_for_user` gained an optional
  `offset` (existing `page`/`size` callers unchanged) to back readiness pagination.

## Verified OFFLINE (no live network / SMTP / DB)
`backend/tests/test_phase4.py` — **19 checks, all green**
(`../.venv/Scripts/python.exe tests/test_phase4.py`; same standalone style as
test_phase2/3, SimpleNamespace stubs, stubbed SMTP transport, AST migration
check). Covers: email message build (text + optional HTML), deterministic +
escaped deadline rendering, graceful degradation when unconfigured, stubbed-
transport send + bulk de-dupe/count, per-recipient error swallowing, lightweight
recipient validation (no `email-validator` dep), section classification, readiness
counts/percent/stage, deadline+urgency annotation (incl. `passed`), urgency
thresholds matching `/deadlines`, calendar event shaping + bucketing, **route
reads packages user-scoped only**, email reminders targeting only email-enabled
subscribers, settings `use_email`/`email_sender` fallback, migration 008 additive
+ reversible. App boots with all 5 `/deadlines` routes registered.

## Review gate (codex) — final SCORE 8/10
codex `exec -s read-only` (gpt-5.5) round 1 = **8/10** (already ≥7). Per the
owner's directive this round, **codex fixed its own findings** via
`codex exec -s workspace-write`; all offline tests + app boot were re-verified
after the edits (no regression). Findings fixed by codex:
- **[High]** `/deadlines/reminders` was callable by any authenticated user and now
  triggers email fan-out → added an `X-Reminder-Secret` header guard compared with
  `hmac.compare_digest` when `REMINDER_CRON_SECRET` is set (still requires an
  authenticated user; preserves behaviour when the secret is unset).
- **[Med]** `send_bulk` could abort the batch on one bad recipient → message
  construction moved inside the per-recipient `try`; bulk skips/logs per recipient.
- **[Med]** no send-time recipient validation → dependency-free validator rejects
  empty / CR-LF / control chars / multiple or comma-separated / display-name /
  no-`@` addresses (defends against header injection from corrupted/imported DB
  rows).
- **[Low]** deadline email `href` allowed any URL scheme → restricted to
  http/https in both HTML and text bodies.
- **[Low]** `/readiness` capped items at 100 but returned the full total → bounded
  limit/offset pagination returning `count` + `total`.

**Confirmed OK by codex:** readiness access is user-scoped (`list_for_user` /
`get_owned`); SMTP secrets come from settings only (no hardcoded creds); email-
unconfigured logs + skips; migration 008 additive + reversible.

> Note: a confirming post-fix re-review was queued but codex hit its API usage
> quota (resets ~03:51). The gate is already satisfied (round-1 8/10) and every
> fix is independently verified by the green offline suite + clean app boot;
> re-running the confirmation review is an optional non-blocking follow-up.

## Needs the live VPS / DB / SMTP (not exercised here)
- Applying migration 008 against real Postgres.
- Real SMTP delivery of deadline reminder emails (set `SMTP_*` / `EMAIL_FROM`).
- The n8n daily cron calling `/deadlines/reminders` with `X-Reminder-Secret` set
  (`REMINDER_CRON_SECRET`) end-to-end across both channels.

## Risks / follow-ups
- Telegram reminders still broadcast to ALL subscribers (pre-existing Phase-2-era
  behaviour, not user-scoped); only the NEW readiness endpoints are user-scoped.
  Per-user reminder targeting would be a future enhancement.
- Email subscriber management (how a user sets/opts-in their `email`) is not yet
  exposed via an endpoint — column + delivery exist; a subscriptions route update
  can follow when the UI needs it.
- `notification_subscriptions` has no `user_id` link to `users`; it keys on
  Telegram IDs. Tying subscriptions to app users is a larger change deferred.
