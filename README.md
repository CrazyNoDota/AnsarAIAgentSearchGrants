# AI Grant Agent

Automated grant sourcing, review, and recommendation system for grant
consultancy work. Scrapes federal/EU/UN grant portals on a daily schedule,
ranks opportunities with AI scoring learned from past staff decisions,
surfaces them through a Next.js dashboard and a Telegram bot, and
notifies subscribed staff of new pending grants.

---

## Live deployment

| Service     | URL                                                  |
|-------------|------------------------------------------------------|
| Web app     | <https://ansar-grants-web.vercel.app>                |
| API         | <https://ansar-grants-api.vercel.app>                |
| API docs    | <https://ansar-grants-api.vercel.app/docs>           |
| Database    | Supabase project `fgmocednhznbqkdftlwk` (ap-southeast-1) |

Default admin login (web): `admin` / `AnsarAdmin2026!`

---

## Architecture

```
                            ┌───────────────────────┐
                            │  Vercel project: web  │
                            │  Next.js 14 dashboard │
                            └──────────┬────────────┘
                                       │ NEXT_PUBLIC_API_URL
                                       ▼
                          ┌──────────────────────────┐
                          │  Vercel project: api     │
                          │                          │
   Telegram ─webhook────► │  /api/telegram   (bot)   │
                          │  /api/index      (FastAPI) ◄──── Web app
                          │  /api/cron/*     (4 jobs) │
                          └────────────┬─────────────┘
                                       │ asyncpg
                                       ▼
                          ┌──────────────────────────┐
                          │  Supabase Postgres 17    │
                          │  pgbouncer pooler :6543  │
                          └──────────────────────────┘
```

Two Vercel projects under the personal account `crazynodota`:

* **`ansar-grants-api`** — Python serverless functions: FastAPI app, Telegram
  webhook receiver, and four daily Cron jobs.
* **`ansar-grants-web`** — Next.js 14 dashboard. Reads `NEXT_PUBLIC_API_URL`
  to talk to the API project.

Both projects share one Supabase Postgres database. The runtime uses the
pgbouncer transaction pooler on port 6543 with `statement_cache_size=0`;
Alembic migrations use the direct connection on port 5432.

---

## Tech stack

| Layer       | Tech                                                         |
|-------------|--------------------------------------------------------------|
| Frontend    | Next.js 14 (App Router), Tailwind, axios                     |
| Backend     | FastAPI, SQLAlchemy 2.x async, asyncpg, Alembic, JWT (python-jose) |
| Bot         | aiogram 3.15 (webhook mode)                                  |
| AI scoring  | Keyword/feature scoring + optional LLM (NVIDIA Qwen3-Coder 480B / OpenAI) |
| DB          | Supabase Postgres 17                                         |
| Hosting     | Vercel (Python + Node serverless functions)                  |
| Scheduling  | Vercel Cron                                                  |
| Local dev   | Docker Compose (Postgres + backend + bot + frontend)         |

---

## Repository layout

```
.
├── api/                       # Vercel Python functions (deployed)
│   ├── index.py               # FastAPI ASGI entry — handles all non-/api/ paths
│   ├── telegram.py            # Telegram webhook receiver (aiogram dispatcher)
│   └── cron/
│       ├── scrape.py          # daily scraping job
│       ├── score.py           # daily AI score recompute
│       ├── reminders.py       # deadline reminders to TELEGRAM_CHAT_ID
│       └── digest.py          # daily digest to /subscribe-d users
│
├── backend/                   # FastAPI app (imported by api/index.py and used in docker-compose)
│   ├── api/routes/            # /auth, /grants, /reviews, /stats, /recommendations, /scraper
│   ├── core/                  # config, security (JWT, bcrypt)
│   ├── database/              # SQLAlchemy engine + Alembic migrations
│   ├── models/                # Grant, Review, User, GrantFeature, NotificationSubscription
│   ├── scraping/              # grants.gov, EU Funding, UNDP scrapers
│   ├── scheduler/             # APScheduler (local dev only — RUN_SCHEDULER=1)
│   ├── services/              # business logic: grant_service, review_service, ai_service, …
│   ├── app/seed.py            # `python -m app.seed` creates the admin user
│   └── main.py                # FastAPI entry for local dev
│
├── bot/                       # aiogram bot (handlers shared between webhook and polling)
│   ├── bot.py                 # long-poll entry for local dev
│   ├── handlers/              # start, grants, reviews, search, subscribe
│   ├── keyboards/             # inline keyboards for approve/reject + pagination
│   ├── middlewares/auth.py    # StaffAuthMiddleware (TELEGRAM_ALLOWED_USERS allowlist)
│   ├── api_client.py          # HTTP client to the FastAPI backend
│   └── config.py
│
├── frontend/                  # Next.js dashboard (its own Vercel project)
│   └── src/
│
├── scripts/
│   └── register_telegram_webhook.py   # one-shot helper for setWebhook
│
├── vercel.json                # function timeouts + cron schedule + rewrites
├── requirements.txt           # Python deps for the Vercel api project
├── docker-compose.yml         # Local-dev stack (db, backend, bot, frontend)
├── .env.example
└── README.md
```

---

## Daily Cron schedule (Vercel)

All cron endpoints expect `Authorization: Bearer ${CRON_SECRET}`; Vercel
sends this automatically when `CRON_SECRET` is set as an env var.

| Time (UTC) | Path                  | What it does                                                |
|-----------:|-----------------------|-------------------------------------------------------------|
| 02:00      | `/api/cron/scrape`    | Run all scrapers, dedupe by `source_url`, insert new grants |
| 03:00      | `/api/cron/score`     | Recompute `ai_score` for every pending grant                |
| 08:00      | `/api/cron/reminders` | DM `TELEGRAM_CHAT_ID` for grants with deadline 7/3/1 d away |
| 09:00      | `/api/cron/digest`    | DM each `/subscribe`-d user a digest of pending grants from the last 24 h |

---

## Telegram bot commands

The bot is a webhook on the API project. Updates from Telegram POST to
`https://ansar-grants-api.vercel.app/api/telegram` and run through
`StaffAuthMiddleware`, which rejects any update from a user whose ID is
not in `TELEGRAM_ALLOWED_USERS`.

| Command           | Description                                              |
|-------------------|----------------------------------------------------------|
| `/start`          | Welcome + stats                                          |
| `/pending`        | Browse pending grants with ✅ Approve / ❌ Reject buttons |
| `/approved`       | List approved grants                                     |
| `/rejected`       | List rejected grants                                     |
| `/search <query>` | Keyword search                                           |
| `/recommend <q>`  | LLM-powered semantic recommendations                     |
| `/subscribe`      | Opt in to the daily digest at 09:00 UTC                  |
| `/unsubscribe`    | Opt out of the digest                                    |
| `/notifications`  | Show current digest subscription status                  |
| `/help`           | Help text                                                |

The approve/reject buttons hit `POST /grants/{id}/review` in the API,
which updates `grant.status`, writes a row to `reviews`, and triggers
`ai_service.update_scores_after_review` to refresh feature weights.

---

## API endpoints

Full interactive docs live at <https://ansar-grants-api.vercel.app/docs>.

| Method | Path                                      | Description                                |
|--------|-------------------------------------------|--------------------------------------------|
| POST   | `/auth/login`                             | Form-encoded `username`/`password` → JWT  |
| GET    | `/health`                                 | Liveness check (no auth)                   |
| GET    | `/grants`                                 | List with `status`, `search`, `country`, `category`, pagination |
| GET    | `/grants/{id}`                            | Single grant                               |
| POST   | `/grants`                                 | Create grant (auth)                        |
| POST   | `/grants/{id}/review`                     | Decision: `approved` or `rejected` (auth)  |
| GET    | `/stats`                                  | `{pending, approved, rejected, total}`     |
| GET    | `/recommendations?q=...`                  | LLM recommendations                        |
| GET    | `/recommendations/{id}/summarize`         | LLM-generated summary for one grant        |
| POST   | `/scraper/run`                            | Manual trigger — runs synchronously        |

All authenticated routes require `Authorization: Bearer <jwt>`.

---

## Environment variables

`api` project (production):

| Var                          | Purpose                                                           |
|------------------------------|-------------------------------------------------------------------|
| `DATABASE_URL`               | Supabase pooler URL on port 6543 (NO `?pgbouncer=true` query)     |
| `SECRET_KEY`                 | JWT signing key (32 bytes hex)                                    |
| `ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT settings                                       |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD`         | Seed admin credentials                             |
| `TELEGRAM_BOT_TOKEN`         | Bot token from @BotFather                                         |
| `TELEGRAM_CHAT_ID`           | Target chat for reminder notifications                            |
| `TELEGRAM_ALLOWED_USERS`     | Comma-separated user IDs allowed to use the bot                   |
| `TELEGRAM_WEBHOOK_SECRET`    | Verified against `X-Telegram-Bot-Api-Secret-Token` header         |
| `NVIDIA_API_KEY` / `NVIDIA_BASE_URL` / `NVIDIA_MODEL` | Qwen3-Coder via NVIDIA's OpenAI-compatible endpoint |
| `OPENAI_API_KEY`             | Optional fallback if NVIDIA key absent                            |
| `BACKEND_URL`                | Same as the api project's URL — bot's HTTP client uses it         |
| `CORS_ORIGINS`               | Comma-separated list, e.g. `https://ansar-grants-web.vercel.app`  |
| `CRON_SECRET`                | Required by every `/api/cron/*` endpoint                          |

`web` project (production):

| Var                    | Value                                              |
|------------------------|----------------------------------------------------|
| `NEXT_PUBLIC_API_URL`  | `https://ansar-grants-api.vercel.app` (no trailing slash) |

For local dev see `.env.example`. The `RUN_SCHEDULER=1` flag is set in
`docker-compose.yml` so APScheduler runs in-process during dev (it's a no-op
on Vercel since Cron handles scheduling).

---

## Local development

### Prerequisites
* Docker Desktop (running)
* `.env` populated from `.env.example`

### Start the full stack

```bash
docker compose up --build
```

| Service        | URL                                  |
|----------------|--------------------------------------|
| Backend API    | <http://localhost:8000>              |
| Swagger docs   | <http://localhost:8000/docs>         |
| Dashboard      | <http://localhost:3000>              |
| Postgres       | `localhost:5432`                     |
| Telegram bot   | long-polling (no public URL needed)  |

The backend container runs `alembic upgrade head` and `python -m app.seed`
on startup, so a fresh DB gets schema + admin user automatically.

### Reset local DB

```bash
docker compose down -v   # wipes the volume
docker compose up --build
```

### Switching the bot between webhook (prod) and polling (dev)

The local container starts the bot in polling mode. Telegram only allows
one consumer at a time, so before running locally, delete the production
webhook:

```bash
python scripts/register_telegram_webhook.py --delete --token <BOT_TOKEN>
```

After the local session, re-register:

```bash
python scripts/register_telegram_webhook.py \
  --token  <BOT_TOKEN> \
  --url    https://ansar-grants-api.vercel.app/api/telegram \
  --secret <TELEGRAM_WEBHOOK_SECRET>
```

---

## Database & migrations

* ORM: SQLAlchemy 2.x with `asyncio` extension and asyncpg driver.
* Migrations: Alembic — `backend/database/migrations/`.
* Runtime connection: Supabase pooler on port **6543** (transaction mode,
  pgbouncer). The runtime auto-detects this and switches to `NullPool`
  with `statement_cache_size=0`.
* Migrations connect on port **5432** (direct, no pooler) via the
  `DIRECT_URL` env var, because pgbouncer + asyncpg prepared statements
  can't run DDL.

### Apply migrations to Supabase from your machine

```powershell
$env:DIRECT_URL  = "postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres"
$env:DATABASE_URL = $env:DIRECT_URL
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.seed
```

### Generate a new migration

```bash
cd backend
alembic revision -m "describe change" --autogenerate
# inspect the generated file in database/migrations/versions/, then:
alembic upgrade head
```

### Current migration history

* `001_initial` — `users`, `grants`, `reviews`, `grant_features`
* `002_notif_sub` — `notification_subscriptions` (one row per subscriber)

---

## Deployment

Both projects deploy via the Vercel CLI. The `vercel.json` at the repo
root configures the api project; `frontend/` deploys with default Next.js
settings.

```powershell
$env:VERCEL_TOKEN = "<your-token>"

# API project
vercel deploy --prod --yes --token $env:VERCEL_TOKEN

# Web project
cd frontend
vercel deploy --prod --yes --token $env:VERCEL_TOKEN
```

Env vars are managed via the Vercel dashboard or `vercel env add ...`.
Changing an env var requires a redeploy for it to take effect on running
functions.

### URL routing on the API project

`vercel.json` rewrites everything that isn't already `/api/...` to
`/api/index`, so FastAPI sees its original routes (`/auth/login`,
`/grants`, `/health`, …). The `/api/telegram` and `/api/cron/*` files
are reached directly without rewriting.

---

## Active scrapers

All scrapers run concurrently via `asyncio.gather` in
`backend/scraping/runner.py` and dedupe inserts on `source_url`.

| Source              | What it covers                                  | Auth | Per-run cap |
|---------------------|-------------------------------------------------|------|-------------|
| `grants.gov`        | US federal funding opportunities (DoD, DoS, DoE, USDA, NIH, etc.) | none | 50          |
| `federal_register`  | US grant notices across every federal agency, filtered by NOFO-style title keywords | none | up to 50 (filtered) |
| `world_bank`        | World Bank development projects (190+ countries) | none | 50          |
| `nsf`               | US National Science Foundation awards            | none | 50          |

Sources audited and **dropped** because the underlying endpoints either
404, return SPA shells, or block scrapers: EU Funding & Tenders portal,
UNDP procurement RSS, ADB/AfDB project feeds, GCF, GEF, IDB, Australia
GrantConnect, UKRI Funding Finder. They can be re-added if their public
endpoints come back.

## Adding a new scraper

1. Create `backend/scraping/<source>.py`.
2. Inherit from `BaseScraper`, implement `async def scrape() -> list[GrantData]`.
3. Add an instance to `ALL_SCRAPERS` in `backend/scraping/runner.py`.
4. Make sure `source_url` is the canonical landing page — it's the
   primary key for dedup.

```python
class MySourceScraper(BaseScraper):
    name = "my_source"

    async def scrape(self) -> list[GrantData]:
        # fetch + parse
        return [GrantData(title="...", source_url="...")]
```

---

## Operational notes

* **Bot won't respond if `TELEGRAM_ALLOWED_USERS` is empty.** The
  middleware silently drops every update from non-allowlisted users.
  Set the env var to your numeric Telegram ID (get it from `@userinfobot`)
  and redeploy.
* **`TELEGRAM_CHAT_ID` is for the broadcast channel.** Reminders fire only
  if it's set; the per-user digest uses the subscriptions table instead.
* **Supabase free tier auto-pauses the database after a week of no
  activity.** If `/health` keeps working but DB queries 500, check the
  Supabase dashboard and resume the project.
* **Function size limit (Vercel Hobby): 250 MB unzipped.** Adding heavy
  deps like Playwright will break the build — keep the api project
  serverless-friendly and run heavy scraping off-platform if needed.
* **Vercel Cron only fires on production deployments**, not previews.

---

## Known limitations & future work

* **Bot HTTP roundtrip overhead.** Telegram callback handlers in
  `bot/handlers/*` call the FastAPI backend through `api_client.py`
  rather than touching the DB directly. On Vercel both run in the same
  project, so each callback triggers two cold starts. Refactoring the
  handlers to use the shared `AsyncSessionLocal` (as `subscribe.py`
  already does) would halve perceived latency.
* **EU Funding / UNDP scrapers returned 0 grants** in the last run.
  Their HTML structure may have changed and they need an audit.
* **No automated tests yet.** Adding pytest coverage for the scrapers
  and the review service would catch regressions before deploy.

---

## Useful one-liners

Run the scraper manually and view the count:

```powershell
$cs = "<CRON_SECRET>"
Invoke-RestMethod `
  -Uri "https://ansar-grants-api.vercel.app/api/cron/scrape" `
  -Headers @{ Authorization = "Bearer $cs" } -TimeoutSec 200
```

Pull all pending grants as JSON:

```powershell
$j = (Invoke-RestMethod -Uri "https://ansar-grants-api.vercel.app/auth/login" `
  -Method Post -Body @{ username="admin"; password="AnsarAdmin2026!" }).access_token
Invoke-RestMethod -Uri "https://ansar-grants-api.vercel.app/grants?status=pending&size=100" `
  -Headers @{ Authorization = "Bearer $j" }
```

Re-register the Telegram webhook after rotating the bot token:

```bash
python scripts/register_telegram_webhook.py \
  --token  <NEW_TOKEN> \
  --url    https://ansar-grants-api.vercel.app/api/telegram \
  --secret <TELEGRAM_WEBHOOK_SECRET>
```
