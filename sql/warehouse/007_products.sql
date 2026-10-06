-- raw_stage for products (Phase 2C). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS raw_stage;

CREATE TABLE IF NOT EXISTS raw_stage.products (
  product_id text NOT NULL,
  product_category_name text,
  product_name_lenght integer,
  product_description_lenght integer,
  product_photos_qty integer,
  product_weight_g integer,
  product_length_cm integer,
  product_height_cm integer,
  product_width_cm integer,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (product_id, source_updated_at)
);
