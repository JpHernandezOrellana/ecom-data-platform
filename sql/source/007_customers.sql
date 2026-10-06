-- source for customers (Phase 2C slice 2). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS source.customers (
  customer_id text PRIMARY KEY,
  customer_unique_id text NOT NULL,
  customer_zip_code_prefix text NOT NULL,
  customer_city text NOT NULL,
  customer_state text NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_customers_cursor
  ON source.customers (source_updated_at, customer_id);
