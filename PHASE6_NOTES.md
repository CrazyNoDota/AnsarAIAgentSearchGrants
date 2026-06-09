# Phase 6 — Deploy + hardening (PREP ONLY)

Status: **PREP DONE. NOTHING DEPLOYED LIVE.** No SSH/network to any server, no
containers started, no migrations applied. Artifacts written + validated offline
+ codex-gated. The live deploy is owner-driven (see checklist at the bottom).

Spec: `UnifiedFolderForAnsarStartupAIagents/docs/00-server-infrastructure.md`.
Target VPS: `31.210.174.74`, Ubuntu 24.04, 4 vCPU / 4 GB / 80 GB, no domain yet.

---

## What was produced

Under `deploy/`:
- `shared/docker-compose.yml` — shared Postgres16+pgvector, Redis7, Caddy.
- `shared/init-db.sh` — first-boot: create `grants_db` + `grants_user`, enable
  `vector`/`pg_trgm`, and create the `n8n` schema owned by `grants_user`.
- `shared/Caddyfile` — reverse proxy; IP/HTTP now, commented domain/TLS block.
- `shared/.env.example` — shared secrets placeholders (no real secrets).
- `grants/docker-compose.yml` — backend, bot, n8n, optional on-demand
  browser-worker, and a shared persistent `camoufox_cache` volume.
- `grants/.env.example` — every var the stack needs, placeholders only.
- `provision.sh` — owner-run host hardening (deploy user, Docker, swap, ufw,
  fail2ban, /opt/ansar layout, shared net).
- `backup.sh` — nightly `pg_dump` of `grants_db` + N-day rotation + cron line.
- `MIGRATION-RUNBOOK.md` — first live DB bring-up (vector ext, 001→009, camoufox
  fetch, seed, rollback).

Plus:
- `.github/workflows/deploy.yml` — push-to-main → SSH deploy (Variant B),
  shared-stack file refresh, and manual `workflow_dispatch`.

The existing single-stack `docker-compose.yml`, `nginx/`, and the `vps_*.py`
scripts were **left untouched** (the working prod stack is undisturbed).

---

## Security improvements over the current single-stack compose

| Area | Current `docker-compose.yml` | Phase 6 artifacts |
|------|------------------------------|-------------------|
| Postgres port | publishes `5432:5432` to the internet | **no host port** — only on `ansar_shared` |
| Redis port | publishes `6379:6379` | **no host port** |
| n8n | publishes `5678:5678` raw, default password `n8n_admin_2026` | **no host port**; reached via Caddy `/n8n/` behind **bcrypt basic-auth**; password required (`:?`), no default |
| TLS | nginx HTTP-only | **Caddy**, auto-Let's Encrypt turn-key (uncomment domain block) |
| User | everything as root | **non-root `deploy`** user, key-only SSH, root/password login disabled |
| Firewall | none (or 22/80/**5678** in deploy.sh) | **ufw 22/80/443 only** |
| Intrusion | none | **fail2ban** on sshd |
| Backups | none | nightly `pg_dump` + 14-day rotation |
| OOM safety | none (4 GB box) | **3 GB swap** + `vm.swappiness=10` |
| Browser worker | n/a | on-demand, `mem_limit: 1.5g`, `restart: "no"` |
| Secrets | committed-ish defaults in compose | placeholders only; required vars fail-fast via `:?`; real `.env` git-ignored, server-only |
| DB isolation | single DB | dedicated `grants_db` + least-priv `grants_user` |
| Edge body limit | none (Phase 3 residual) | Caddy `request_body max_size 25MB` |
| Secret in env | n8n default pw, no reminder secret enforcement | `REMINDER_CRON_SECRET` placeholder wired for the n8n cron |
| Seed robustness | `python -m app.seed` fatal in start chain | seed made **non-fatal** (`|| echo WARN`); migrations stay fatal |

---

## Runtime-code observations (FLAGGED, not fixed — runtime code untouched)

- `python -m app.seed` is **valid**: `backend/app/seed.py` exists and the
  container workdir is `/app` (= `backend/`). It self-inserts `/app` on sys.path.
  No mismatch. Seed is still made non-fatal in the start command as a safety net.
- Caddy serves the WHOLE backend site (it exposes `/health`, `/docs`, `/api/*`,
  route-prefixed paths). The old nginx mapped `/api/` → backend root; clients
  that hard-coded `/api/...` paths should be checked against the app's actual
  route prefixes at deploy time (informational).
- `CORS_ORIGINS` should include the public origin (VPS IP now, domain later) if
  a browser frontend calls the API directly.

---

## Left for live deploy day (owner-run; intentionally NOT done here)

- Run `provision.sh` on the VPS (needs root + the owner's SSH public key).
- Create the real `.env` files from the `.example`s with real secrets.
- Set GitHub Actions Secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`,
  `VPS_SSH_PORT` (optional), and `VPS_SSH_KNOWN_HOSTS` (optional pinned
  known_hosts line; recommended over runtime keyscan trust).
- Bring up shared then grants; apply migrations 001→009 (auto via backend start
  or manual `alembic upgrade head`); `python -m camoufox fetch` persists in
  the shared `camoufox_cache` volume.
- Keep `N8N_ENCRYPTION_KEY` stable and back up the `n8n_data` volume; losing the
  key makes stored n8n credentials unrecoverable.
- Toggle the Caddyfile domain/TLS block when a domain/subdomain exists. n8n
  domain cutover also requires `N8N_PATH=/`, `N8N_SECURE_COOKIE=true`, and
  HTTPS `N8N_PUBLIC_URL` / `WEBHOOK_URL` values; do not change the current
  `/n8n/` IP-mode config until then.
- Install the backup cron line from `backup.sh`.
- Future hardening: non-root container users and read-only container filesystems
  are documented as out of scope for now; the current Python image is root-based.
- Decide the git strategy for committing Phases 1–6 (the repo has pre-existing
  unrelated uncommitted changes — git was left untouched this phase).

---

## Pre-deploy checklist

1. [ ] DNS (optional, when domain exists): A-record(s) → 31.210.174.74.
2. [ ] `provision.sh` run; `ssh deploy@31.210.174.74` works with key.
3. [ ] `systemctl restart ssh` (locks out root/password) after key verified.
4. [ ] `ansar_shared` network exists (`docker network ls`).
5. [ ] `shared/.env` + `grants/.env` filled; GRANTS_* match POSTGRES_* across them.
6. [ ] N8N_BASICAUTH_HASH generated via `caddy hash-password`.
7. [ ] shared stack up; `\dx` shows `vector` + `pg_trgm` in `grants_db`.
8. [ ] grants stack up; `alembic current` = `009_phase5_knowledge_base`.
9. [ ] admin seeded; `curl http://127.0.0.1/health` OK via Caddy.
10. [ ] camoufox fetched before any live browser scraping.
11. [ ] backup cron installed; first manual `backup.sh` run succeeds.
12. [ ] GitHub Secrets set, ideally including pinned `VPS_SSH_KNOWN_HOSTS`; push to main triggers a successful deploy run.
13. [ ] ufw shows only 22/80/443; no host ports for db/redis/n8n.

---

## Validation (offline) + codex gate

**codex gate: 8/10** (gate ≥7 met). Loop: r1=7 → codex self-fixed all 6 findings
→ r2=6 (regression: new `N8N_DB_*` vars not passed to the shared `db` container)
→ codex self-fixed → r3=8 → one trailing Med (nightly `pg_dump` as `grants_user`
could fail on n8n-owned objects) self-fixed (dump as `ansar_admin`). SSH
staged-not-applied is accepted by design (anti-lockout; `sshd -t` validated +
manual `systemctl restart ssh`). Each round re-verified: `bash -n` on all shell
scripts + YAML parse on both compose files and the workflow — all clean. No real
secrets in any committed artifact (placeholders only). See PROGRESS-HANDOFF.md
"Phase 6" section for the per-finding detail.

Net fixes applied this gate (vs. the original prep): CI requires
`VPS_SSH_KNOWN_HOSTS` (no ssh-keyscan TOFU) + key via env+printf; runbook compose
commands carry `--env-file`; **dedicated least-priv `n8n_user`** owns the `n8n`
schema (separate from `grants_user`); backup dumps as `ansar_admin` (reads all
schemas) and restore reassigns ownership back to `grants_user`; `provision.sh`
validates `SWAP_SIZE` and the staged sshd config (`sshd -t`).
