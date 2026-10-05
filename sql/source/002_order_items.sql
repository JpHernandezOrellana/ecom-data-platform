-- Source operational schema for order_items (simulator-owned). ADR-006.
CREATE TABLE IF NOT EXISTS source.order_items (
  order_id text NOT NULL,
  order_item_id integer NOT NULL,
  source_cursor_key text GENERATED ALWAYS AS (
    order_id || ':' || lpad(order_item_id::text, 4, '0')
  ) STORED,
  product_id text NOT NULL,
  seller_id text NOT NULL,
  shipping_limit_at timestamptz NOT NULL,
  shipping_limit_at_source_text text NOT NULL,
  shipping_limit_at_timezone_resolution text NOT NULL,
  price numeric(18,2) NOT NULL,
  freight_value numeric(18,2) NOT NULL,
  source_created_at timestamptz NOT NULL,
  source_updated_at timestamptz NOT NULL,
  PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX IF NOT EXISTS idx_order_items_cursor
  ON source.order_items (source_updated_at, source_cursor_key);
