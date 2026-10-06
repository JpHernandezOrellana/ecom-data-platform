-- raw_stage for customers (Phase 2C slice 2). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS raw_stage;

CREATE TABLE IF NOT EXISTS raw_stage.customers (
  customer_id text NOT NULL,
  customer_unique_id text NOT NULL,
  customer_zip_code_prefix text NOT NULL,
  customer_city text NOT NULL,
  customer_state text NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (customer_id, source_updated_at)
);
