from __future__ import annotations

import argparse
from datetime import UTC, datetime

from .config import Settings
from .db import connect


def main() -> None:
    p = argparse.ArgumentParser(description="Deterministic order mutations (demo/test)")
    p.add_argument("--ts", default="2018-10-21T00:00:00+00:00")
    args = p.parse_args()
    settings = Settings.from_env()
    ts = datetime.fromisoformat(args.ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    import os

    dsn = os.environ.get("SOURCE_DSN", settings.source_dsn)
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            # Deterministic new order
            cur.execute(
                """INSERT INTO source.orders (order_id, customer_id, order_status,
                   order_purchase_at, order_purchase_at_source_text, order_purchase_at_timezone_resolution,
                   order_approved_at, order_approved_at_source_text, order_approved_at_timezone_resolution,
                   order_delivered_carrier_at, order_delivered_carrier_at_source_text, order_delivered_carrier_at_timezone_resolution,
                   order_delivered_customer_at, order_delivered_customer_at_source_text, order_delivered_customer_at_timezone_resolution,
                   order_estimated_delivery_at, order_estimated_delivery_at_source_text, order_estimated_delivery_at_timezone_resolution,
                   source_created_at, source_updated_at)
                   VALUES (%s,%s,'created',%s,%s,'synthetic_aware',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,%s,%s,'synthetic_aware',%s,%s)
                   ON CONFLICT (order_id) DO NOTHING""",
                (
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    ts,
                    args.ts,
                    ts,
                    args.ts,
                    ts,
                    ts,
                ),
            )
            # Deterministic status update of an existing order (latest by key)
            cur.execute("SELECT order_id FROM source.orders ORDER BY order_id LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE source.orders SET order_status='shipped', source_updated_at=%s WHERE order_id=%s",
                    (ts, row[0]),
                )
        conn.commit()
    print(f"mutate ok ts={args.ts}")


if __name__ == "__main__":
    main()
