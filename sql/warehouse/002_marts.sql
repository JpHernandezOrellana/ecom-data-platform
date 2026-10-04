CREATE SCHEMA IF NOT EXISTS raw_stage;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold_candidate;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS raw_stage.orders (
  order_id text NOT NULL,
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
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (order_id, source_updated_at)
);
