-- Source operational schema (simulator-owned).
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS source.orders (
  order_id text PRIMARY KEY,
  customer_id text NOT NULL,
  order_status text NOT NULL,
  order_purchase_at timestamptz NOT NULL,
  order_purchase_at_source_text text NOT NULL,
  order_purchase_at_timezone_resolution text NOT NULL,
  order_approved_at timestamptz,
  order_approved_at_source_text text,
  order_approved_at_timezone_resolution text,
  order_delivered_carrier_at timestamptz,
  order_delivered_carrier_at_source_text text,
  order_delivered_carrier_at_timezone_resolution text,
  order_delivered_customer_at timestamptz,
  order_delivered_customer_at_source_text text,
  order_delivered_customer_at_timezone_resolution text,
  order_estimated_delivery_at timestamptz NOT NULL,
  order_estimated_delivery_at_source_text text NOT NULL,
  order_estimated_delivery_at_timezone_resolution text NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_cursor
  ON source.orders (source_updated_at, order_id);
