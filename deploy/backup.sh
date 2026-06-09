#!/usr/bin/env bash
# ============================================================
# Ansar — nightly Postgres backup (grants_db) with N-day rotation
# Target on VPS: /opt/ansar/backup.sh   (run by cron as the deploy user)
#
# Dumps grants_db from the shared Postgres container via `docker exec`
# (Postgres has NO host port, so we go through the container) to
# /opt/ansar/backups, gzip-compressed, and prunes dumps older than RETENTION.
#
# Install the cron line (run once, as the deploy user):
#   ( crontab -l 2>/dev/null; echo "30 3 * * * /opt/ansar/backup.sh >> /opt/ansar/backups/backup.log 2>&1" ) | crontab -
# -> every day at 03:30 server time.
# ============================================================
set -euo pipefail

PG_CONTAINER="${PG_CONTAINER:-ansar_db}"
DB_NAME="${DB_NAME:-grants_db}"
# Default to the superuser so pg_dump can read every schema, including
# n8n-owned objects; keep DB_USER overridable for one-off maintenance.
DB_USER="${DB_USER:-ansar_admin}"
BACKUP_DIR="${BACKUP_DIR:-/opt/ansar/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql.gz"
TMP="${OUT}.partial"

echo "[backup] $(date -Is) dumping ${DB_NAME} -> ${OUT}"

# pg_dump inside the container as DB_USER; stream through gzip on the host.
# Write to a .partial file first so a crash never leaves a truncated "good"
# backup.
if docker exec -i "${PG_CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" --no-owner --clean --if-exists \
     | gzip > "${TMP}"; then
  mv "${TMP}" "${OUT}"
  echo "[backup] OK: $(du -h "${OUT}" | cut -f1)"
else
  echo "[backup] ERROR: pg_dump failed; removing partial" >&2
  rm -f "${TMP}"
  exit 1
fi

# Rotation: delete dumps older than RETENTION_DAYS.
echo "[backup] pruning dumps older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name "${DB_NAME}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "[backup] done."

# Restore (manual, when needed):
#   # The dump uses --clean and may include DROP/CREATE EXTENSION statements
#   # for vector/pg_trgm. Restore as ansar_admin so extension DDL succeeds
#   # under ON_ERROR_STOP, then repair ownership back to the app role.
#   gunzip -c /opt/ansar/backups/grants_db_YYYYMMDD_HHMMSS.sql.gz \
#     | docker exec -i ansar_db psql -v ON_ERROR_STOP=1 -U ansar_admin -d grants_db
#   docker exec -i ansar_db psql -v ON_ERROR_STOP=1 -U ansar_admin -d grants_db \
#     -c "REASSIGN OWNED BY ansar_admin TO grants_user;"
