from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow.parquet as pq

from .config import Settings
from .db import connect


def main() -> None:
    p = argparse.ArgumentParser(description="Idempotent Bronze -> raw_stage load")
    p.parse_args()
    settings = Settings.from_env()
    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        cur.execute("SELECT batch_id, manifest_path FROM control.batch WHERE status='committed'")
        batches = cur.fetchall()
        for batch_id, manifest_path in batches:
            cur.execute(
                "SELECT status FROM control.batch_load WHERE batch_id=%s AND target_schema='raw_stage' AND target_table='orders'",
                (batch_id,),
            )
            r = cur.fetchone()
            if r and r[0] == "loaded":
                continue
            base = Path(manifest_path).parent
            pq_path = base / "bronze" / "accepted.parquet"
            try:
                table = pq.read_table(pq_path)
            except OSError:
                table = None
            n = 0
            if table is not None and table.num_rows:
                for row in table.to_pylist():
                    if not row:
                        continue
                    cur.execute(
                        """INSERT INTO raw_stage.orders (order_id, customer_id, order_status,
                           order_purchase_at, order_approved_at, order_delivered_carrier_at,
                           order_delivered_customer_at, order_estimated_delivery_at,
                           source_created_at, source_updated_at, batch_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (order_id, source_updated_at) DO NOTHING""",
                        (
                            row.get("order_id"),
                            row.get("customer_id"),
                            row.get("order_status"),
                            row.get("order_purchase_at"),
                            row.get("order_approved_at"),
                            row.get("order_delivered_carrier_at"),
                            row.get("order_delivered_customer_at"),
                            row.get("order_estimated_delivery_at"),
                            row.get("source_created_at") or row.get("source_updated_at"),
                            row.get("source_updated_at"),
                            batch_id,
                        ),
                    )
                    n += 1
            cur.execute(
                """INSERT INTO control.batch_load (batch_id, target_schema, target_table, status, loaded_rows)
                   VALUES (%s,'raw_stage','orders','loaded',%s)
                   ON CONFLICT (batch_id, target_schema, target_table) DO UPDATE SET status='loaded', loaded_rows=%s""",
                (batch_id, n, n),
            )
        wconn.commit()
    print("load ok")


if __name__ == "__main__":
    main()
