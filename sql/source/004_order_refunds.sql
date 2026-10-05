-- Synthetic refund events (simulator-owned, ADR-005). Not derived from Olist data.
CREATE TABLE IF NOT EXISTS source.order_refunds (
  refund_id text PRIMARY KEY,
  order_id text NOT NULL,
  payment_sequential integer NOT NULL,
  refunded_amount numeric(18,2) NOT NULL,
  refund_reason text NOT NULL,
  refunded_at timestamptz NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  FOREIGN KEY (order_id, payment_sequential)
    REFERENCES source.order_payments (order_id, payment_sequential)
);

CREATE INDEX IF NOT EXISTS idx_order_refunds_cursor
  ON source.order_refunds (source_updated_at, refund_id);
