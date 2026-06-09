#!/bin/bash
# ============================================================
# Ansar shared Postgres — first-boot init (per-project DB + role + extensions)
#
# Runs ONCE, automatically, by the postgres image entrypoint when the data
# volume is empty (mounted at /docker-entrypoint-initdb.d). On an existing
# volume it is NOT re-run — apply changes manually via psql then.
#
# Creates the grants project database + dedicated least-privilege roles,
# enables the vector / pg_trgm extensions inside that database, and creates the
# n8n schema owned by the n8n role.
# ============================================================
set -euo pipefail

GRANTS_DB="${GRANTS_DB:-grants_db}"
GRANTS_DB_USER="${GRANTS_DB_USER:-grants_user}"
GRANTS_DB_PASSWORD="${GRANTS_DB_PASSWORD:?GRANTS_DB_PASSWORD must be set}"
N8N_DB_USER="${N8N_DB_USER:-n8n_user}"
N8N_DB_PASSWORD="${N8N_DB_PASSWORD:?N8N_DB_PASSWORD must be set}"

validate_pg_identifier() {
    local name="$1"
    local value="$2"
    if [[ ! "${value}" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
        echo "[init-db] ERROR: ${name} must be a simple PostgreSQL identifier (letters, digits, underscore; starts with letter/underscore; max 63 chars)." >&2
        exit 1
    fi
}

validate_pg_identifier "GRANTS_DB" "${GRANTS_DB}"
validate_pg_identifier "GRANTS_DB_USER" "${GRANTS_DB_USER}"
validate_pg_identifier "N8N_DB_USER" "${N8N_DB_USER}"

echo "[init-db] creating roles '${GRANTS_DB_USER}', '${N8N_DB_USER}' and database '${GRANTS_DB}'..."

# Connect to the bootstrap database as the superuser created by the image.
psql -v ON_ERROR_STOP=1 \
    -v grants_db_user="${GRANTS_DB_USER}" \
    -v grants_db_password="${GRANTS_DB_PASSWORD}" \
    -v n8n_db_user="${N8N_DB_USER}" \
    -v n8n_db_password="${N8N_DB_PASSWORD}" \
    --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'grants_db_user', :'grants_db_password')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'grants_db_user')\gexec
    SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'n8n_db_user', :'n8n_db_password')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'n8n_db_user')\gexec
EOSQL

# CREATE DATABASE cannot run inside the DO block; guard with a gexec pattern.
psql -v ON_ERROR_STOP=1 \
    -v grants_db="${GRANTS_DB}" \
    -v grants_db_user="${GRANTS_DB_USER}" \
    --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    SELECT format('CREATE DATABASE %I OWNER %I', :'grants_db', :'grants_db_user')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'grants_db')\gexec
EOSQL

# Enable extensions INSIDE the project database (superuser required for CREATE
# EXTENSION). pgvector + pg_trgm.
psql -v ON_ERROR_STOP=1 \
    -v grants_db_user="${GRANTS_DB_USER}" \
    -v n8n_db_user="${N8N_DB_USER}" \
    --username "${POSTGRES_USER}" --dbname "${GRANTS_DB}" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    SELECT format('GRANT ALL ON SCHEMA public TO %I', :'grants_db_user')\gexec
    SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'n8n_db_user')\gexec
    -- n8n runs `CREATE SCHEMA IF NOT EXISTS n8n` on every startup, which needs
    -- CREATE on the database (CONNECT alone => "permission denied for database").
    SELECT format('GRANT CREATE ON DATABASE %I TO %I', current_database(), :'n8n_db_user')\gexec
    SELECT format('CREATE SCHEMA IF NOT EXISTS n8n AUTHORIZATION %I', :'n8n_db_user')\gexec
    SELECT format('ALTER SCHEMA n8n OWNER TO %I', :'n8n_db_user')\gexec
    SELECT format('GRANT ALL ON SCHEMA n8n TO %I', :'n8n_db_user')\gexec
EOSQL

echo "[init-db] done: ${GRANTS_DB} ready with vector + pg_trgm + n8n schema."
