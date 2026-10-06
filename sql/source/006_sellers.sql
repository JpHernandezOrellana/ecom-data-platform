-- raw_stage for sellers (Phase 2C). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS source.sellers (
  seller_id text PRIMARY KEY,
  seller_zip_code_prefix text NOT NULL,
  seller_city text NOT NULL,
  seller_state text NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sellers_cursor
  ON source.sellers (source_updated_at, seller_id);
