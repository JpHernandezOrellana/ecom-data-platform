ALTER TABLE raw_stage.orders
  ADD COLUMN IF NOT EXISTS order_purchase_at_source_text text,
  ADD COLUMN IF NOT EXISTS order_purchase_at_timezone_resolution text,
  ADD COLUMN IF NOT EXISTS order_approved_at_source_text text,
  ADD COLUMN IF NOT EXISTS order_approved_at_timezone_resolution text,
  ADD COLUMN IF NOT EXISTS order_delivered_carrier_at_source_text text,
  ADD COLUMN IF NOT EXISTS order_delivered_carrier_at_timezone_resolution text,
  ADD COLUMN IF NOT EXISTS order_delivered_customer_at_source_text text,
  ADD COLUMN IF NOT EXISTS order_delivered_customer_at_timezone_resolution text,
  ADD COLUMN IF NOT EXISTS order_estimated_delivery_at_source_text text,
  ADD COLUMN IF NOT EXISTS order_estimated_delivery_at_timezone_resolution text,
  ADD COLUMN IF NOT EXISTS payload_hash text;

CREATE TABLE IF NOT EXISTS control.backfill_request (
  request_id text PRIMARY KEY,
  source_name text NOT NULL,
  entity_name text NOT NULL,
  cursor_from_updated_at timestamptz NOT NULL,
  cursor_from_key text NOT NULL,
  cursor_to_updated_at timestamptz NOT NULL,
  cursor_to_key text NOT NULL,
  reason text NOT NULL,
  batch_id text,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

ALTER TABLE control.publication
  ADD COLUMN IF NOT EXISTS test_results_path text,
  ADD COLUMN IF NOT EXISTS dbt_manifest_path text,
  ADD COLUMN IF NOT EXISTS tested_at timestamptz;
