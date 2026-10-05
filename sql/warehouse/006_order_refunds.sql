-- raw_stage for order_refunds (Phase 2B). Idempotent migration for existing volumes.
CREATE TABLE IF NOT EXISTS raw_stage.order_refunds (
  refund_id text NOT NULL,
  order_id text NOT NULL,
  payment_sequential integer NOT NULL,
  refunded_amount numeric(18,2) NOT NULL,
  refund_reason text NOT NULL,
  refunded_at timestamptz NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  payload_hash text NOT NULL,
  batch_id text NOT NULL,
  PRIMARY KEY (refund_id, source_updated_at)
);
