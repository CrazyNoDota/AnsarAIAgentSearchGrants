# MIGRATION RUNBOOK — first live DB bring-up (grants)

First-time bring-up of the grants stack on VPS `31.210.174.74`. PREP-ONLY doc:
the owner runs these steps on deploy day. Nothing here has been run live.

Topology recap: ONE shared Postgres (`ansar_db`) on the internal `ansar_shared`
network, with a dedicated `grants_db`, app role `grants_user`, and n8n role
`n8n_user`. Postgres has **no host port** — reach it through the container
(`docker exec ansar_db ...`).

---

## 0. Pre-reqs (host already provisioned)

`provision.sh` has run (deploy user, Docker + compose plugin, `ansar_shared`
network, `/opt/ansar/{shared,grants,backups}`, ufw, swap, fail2ban).

Files in place:
- `/opt/ansar/shared/{docker-compose.yml, Caddyfile, init-db.sh, .env}`
- `/opt/ansar/grants/` = the cloned repo, with `deploy/grants/.env` filled in.

`shared/.env` `GRANTS_DB` / `GRANTS_DB_USER` / `GRANTS_DB_PASSWORD` **must
match** `grants/.env` `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`.
`shared/.env` `N8N_DB_USER` / `N8N_DB_PASSWORD` **must match**
`grants/.env` `N8N_DB_USER` / `N8N_DB_PASSWORD`.

---

## 1. Bring up the shared stack (creates DB + vector extension)

```bash
cd /opt/ansar/shared
docker compose --env-file /opt/ansar/shared/.env -f /opt/ansar/shared/docker-compose.yml up -d db redis caddy
docker compose --env-file /opt/ansar/shared/.env -f /opt/ansar/shared/docker-compose.yml logs -f db
# watch for: "init-db done: grants_db ready with vector + pg_trgm + n8n schema"
```

`init-db.sh` runs automatically **only on a fresh data volume**. It creates
`grants_db` + `grants_user` + `n8n_user` and runs
`CREATE EXTENSION IF NOT EXISTS vector` (+ `pg_trgm`) **inside grants_db**,
then creates the `n8n` schema owned by `n8n_user`. Phase 1/2/5 embeddings + the ivfflat indexes in migration 009
require the vector extension.

### If the data volume already existed (extension not auto-created)
Enable it manually (superuser required for `CREATE EXTENSION`):

```bash
docker exec -it ansar_db psql -U ansar_admin -d grants_db \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
  -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'n8n_user') THEN CREATE ROLE n8n_user LOGIN PASSWORD 'CHANGE_ME_strong_n8n_db_password'; END IF; END \$\$;" \
  -c "GRANT CONNECT ON DATABASE grants_db TO n8n_user;" \
  -c "CREATE SCHEMA IF NOT EXISTS n8n AUTHORIZATION n8n_user;" \
  -c "GRANT ALL ON SCHEMA n8n TO n8n_user;"
```

Verify:
```bash
docker exec -it ansar_db psql -U grants_user -d grants_db -c "\dx"
# expect: vector, pg_trgm
```

---

## 2. Apply migrations 001 -> 009 (`alembic upgrade head`)

The backend container runs `alembic upgrade head` automatically on start
(see `deploy/grants/docker-compose.yml` command). To bring the stack up:

```bash
cd /opt/ansar/grants
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml up -d --build backend
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml logs -f backend
# expect: "Running database migrations..." then the alembic 001..009 chain.
```

Migration chain (additive + reversible; from PROGRESS-HANDOFF.md):
```
001_initial -> 002_notification_subscriptions -> 003_rag_learning ->
004_phase1_filters -> 005_phase2_profiles -> 006_profile_user_scope ->
007_phase3_applications -> 008_phase4_email_channel -> 009_phase5_knowledge_base
```
- `006` adds a NOT NULL `user_id` to `company_profiles` assuming the table is
  empty (true on a fresh DB).
- `009` creates `knowledge_entries` + `knowledge_embeddings`; the latter has a
  `vector(1024)` column + an **ivfflat** index → requires the `vector`
  extension from step 1.

To run migrations manually instead of via the start command:
```bash
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml run --rm backend alembic upgrade head
```

Confirm:
```bash
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml run --rm backend alembic current
# expect: 009_phase5_knowledge_base (head)
```

---

## 3. Seed the admin user

Done best-effort by the start command (`python -m app.seed`; non-fatal if it
fails). `backend/app/seed.py` exists and is import-valid (workdir `/app` =
backend, so `app.seed` resolves). It creates the admin from
`ADMIN_USERNAME`/`ADMIN_PASSWORD`. To run manually:

```bash
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml run --rm backend python -m app.seed
```

> Note flagged (not fixed — runtime code untouched): `app/seed.py` does
> `sys.path.insert(0, "/app")`, which is correct for the container workdir.

---

## 4. camoufox browser blocker fetch (Phase 0 BLOCKER)

Stealth scraping (Phase 1) needs camoufox's patched-Firefox binary, which is
NOT baked into the image. Fetch it inside an on-demand worker before any live
browser scraping:

```bash
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml --profile browser run --rm \
  browser-worker python -m camoufox fetch
```

The fetch writes to the named `camoufox_cache` volume mounted at
`/root/.cache/camoufox` in both `backend` and `browser-worker`, so the browser
binary/cache persists across `--rm` one-shot worker runs and is shared with the
backend image. Browser work is on-demand only — `mem_limit: 1.5g`, not
always-on, per the 4 GB RAM strategy.

---

## 5. Bring up the rest + verify

```bash
cd /opt/ansar/grants
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml up -d backend bot n8n
docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml ps
curl -fsS http://127.0.0.1/health          # via Caddy on :80 -> backend
# n8n: http://31.210.174.74/n8n/  (Caddy basic-auth, then n8n login)
```

Keep `N8N_ENCRYPTION_KEY` stable and back up the `n8n_data` volume; losing the
key makes stored n8n credentials unrecoverable.

---

## 6. Rollback

- **App / migrations:** downgrade one step (all migrations are reversible):
  ```bash
  docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml run --rm backend alembic downgrade -1
  ```
  Roll back to a specific revision: `alembic downgrade 008_phase4_email_channel`.
- **Restore from backup** (see `deploy/backup.sh`):
  The dump uses `--clean`, which can emit `DROP EXTENSION` / `CREATE EXTENSION`
  statements for `vector` and `pg_trgm`. Restore through the Postgres superuser
  `ansar_admin` so extension DDL succeeds under `ON_ERROR_STOP`, then repair
  object ownership back to the app role because the dump is created with
  `--no-owner`.
  ```bash
  gunzip -c /opt/ansar/backups/grants_db_YYYYMMDD_HHMMSS.sql.gz \
    | docker exec -i ansar_db psql -v ON_ERROR_STOP=1 -U ansar_admin -d grants_db
  docker exec -i ansar_db psql -v ON_ERROR_STOP=1 -U ansar_admin -d grants_db \
    -c "REASSIGN OWNED BY ansar_admin TO grants_user;"
  ```
- **Code:** the deploy workflow does `git reset --hard origin/main`; to roll
  back, revert the commit on `main` (re-deploys the prior state), or on the VPS
  `git checkout <prev-sha>` then re-run
  `docker compose --env-file deploy/grants/.env -f deploy/grants/docker-compose.yml up -d --build`.
- **Full reset (DESTRUCTIVE — wipes the shared DB volume):**
  `docker compose --env-file /opt/ansar/shared/.env -f /opt/ansar/shared/docker-compose.yml down -v`. Only on a
  throwaway/fresh box; this deletes Postgres data for ALL projects.
