-- raw_stage for products (Phase 2C). Idempotent migration for existing volumes.
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS source.products (
  product_id text PRIMARY KEY,
  product_category_name text,
  product_name_lenght integer,
  product_description_lenght integer,
  product_photos_qty integer,
  product_weight_g integer,
  product_length_cm integer,
  product_height_cm integer,
  product_width_cm integer,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_cursor
  ON source.products (source_updated_at, product_id);
