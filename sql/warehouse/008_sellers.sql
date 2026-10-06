-- raw_stage for sellers (Phase 2C). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS raw_stage;

CREATE TABLE IF NOT EXISTS raw_stage.sellers (
  seller_id text NOT NULL,
  seller_zip_code_prefix text NOT NULL,
  seller_city text NOT NULL,
  seller_state text NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (seller_id, source_updated_at)
);
