-- Source operational schema for order_payments (simulator-owned). ADR-006.
CREATE TABLE IF NOT EXISTS source.order_payments (
  order_id text NOT NULL,
  payment_sequential integer NOT NULL,
  source_cursor_key text GENERATED ALWAYS AS (
    order_id || ':' || lpad(payment_sequential::text, 4, '0')
  ) STORED,
  payment_type text NOT NULL,
  payment_installments integer NOT NULL,
  payment_value numeric(18,2) NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  PRIMARY KEY (order_id, payment_sequential)
);

CREATE INDEX IF NOT EXISTS idx_order_payments_cursor
  ON source.order_payments (source_updated_at, source_cursor_key);
