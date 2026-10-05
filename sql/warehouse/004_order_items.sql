-- raw_stage for order_items (Phase 2A). Idempotent migration for existing volumes,
-- mirroring 003_phase1_1.sql's pattern.
CREATE TABLE IF NOT EXISTS raw_stage.order_items (
  order_id text NOT NULL,
  order_item_id integer NOT NULL,
  source_cursor_key text NOT NULL,
  product_id text NOT NULL,
  seller_id text NOT NULL,
  shipping_limit_at timestamptz NOT NULL,
  shipping_limit_at_source_text text NOT NULL,
  shipping_limit_at_timezone_resolution text NOT NULL,
  price numeric(18,2) NOT NULL,
  freight_value numeric(18,2) NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (order_id, order_item_id, source_updated_at)
);
