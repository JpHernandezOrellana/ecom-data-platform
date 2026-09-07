CREATE SCHEMA IF NOT EXISTS control;

CREATE TABLE IF NOT EXISTS control.checkpoint (
  source_name text NOT NULL,
  entity_name text NOT NULL,
  cursor_updated_at timestamptz,
  cursor_key text,
  checkpoint_version bigint NOT NULL DEFAULT 1,
  last_committed_batch_id text,
  last_ingestion_run_id text,
  committed_at timestamptz,
  PRIMARY KEY (source_name, entity_name)
);

CREATE TABLE IF NOT EXISTS control.batch (
  batch_id text PRIMARY KEY,
  source_name text NOT NULL,
  entity_name text NOT NULL,
  run_id text NOT NULL,
  run_mode text NOT NULL,
  cursor_before_updated_at timestamptz,
  cursor_before_key text,
  cursor_upper_updated_at timestamptz NOT NULL,
  cursor_upper_key text NOT NULL,
  contract_version text NOT NULL,
  manifest_path text NOT NULL,
  accepted_count bigint NOT NULL,
  rejected_count bigint NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS control.batch_load (
  batch_id text NOT NULL,
  target_schema text NOT NULL,
  target_table text NOT NULL,
  status text NOT NULL,
  loaded_rows bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (batch_id, target_schema, target_table)
);

CREATE TABLE IF NOT EXISTS control.publication (
  product_name text NOT NULL,
  publication_id text NOT NULL,
  candidate_relation text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product_name, publication_id)
);
