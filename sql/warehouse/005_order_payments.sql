-- raw_stage for order_payments (Phase 2B). Idempotent migration for existing volumes.
CREATE TABLE IF NOT EXISTS raw_stage.order_payments (
  order_id text NOT NULL,
  payment_sequential integer NOT NULL,
  source_cursor_key text NOT NULL,
  payment_type text NOT NULL,
  payment_installments integer NOT NULL,
  payment_value numeric(18,2) NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (order_id, payment_sequential, source_updated_at)
);
