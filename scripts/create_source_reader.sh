#!/usr/bin/env bash
# Idempotent creation of the least-privilege source reader role.
# Local-only helper: reads credentials from the environment (see .env.example).
set -euo pipefail

: "${SOURCE_USER:?set SOURCE_USER}"
: "${SOURCE_PASSWORD:?set SOURCE_PASSWORD}"
: "${SOURCE_DB:?set SOURCE_DB}"
: "${SOURCE_READER_USER:?set SOURCE_READER_USER}"
: "${SOURCE_READER_PASSWORD:?set SOURCE_READER_PASSWORD}"

export PGPASSWORD="$SOURCE_PASSWORD"

docker compose exec -T source-postgres psql -U "$SOURCE_USER" -d "$SOURCE_DB" \
  -v ON_ERROR_STOP=1 \
  -v reader_user="$SOURCE_READER_USER" \
  -v source_db="$SOURCE_DB" \
  -v reader_pw="$SOURCE_READER_PASSWORD" <<'SQL'
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader_user')
    THEN format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'reader_user', :'reader_pw')
  ELSE format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'reader_user', :'reader_pw')
END
\gexec
GRANT CONNECT ON DATABASE :"source_db" TO :"reader_user";
GRANT USAGE ON SCHEMA source TO :"reader_user";
GRANT SELECT ON ALL TABLES IN SCHEMA source TO :"reader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA source GRANT SELECT ON TABLES TO :"reader_user";
SQL

echo "source reader '$SOURCE_READER_USER' ready (SELECT-only on schema source)"
