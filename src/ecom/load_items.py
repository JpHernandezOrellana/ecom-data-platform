from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .db import connect, ensure_phase_1_1_warehouse_schema, ensure_phase_2a_warehouse_schema
from .load import _read_committed_bronze


def main() -> None:
    p = argparse.ArgumentParser(description="Idempotent Bronze -> raw_stage load for order_items")
    p.parse_args()
    settings = Settings.from_env()
    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        ensure_phase_1_1_warehouse_schema(wconn)
        ensure_phase_2a_warehouse_schema(wconn)
        cur.execute(
            "SELECT batch_id, manifest_path FROM control.batch "
            "WHERE status='committed' AND entity_name='order_items'"
        )
        batches = cur.fetchall()
        for batch_id, manifest_path in batches:
            cur.execute(
                "SELECT status FROM control.batch_load WHERE batch_id=%s "
                "AND target_schema='raw_stage' AND target_table='order_items'",
                (batch_id,),
            )
            r = cur.fetchone()
            if r and r[0] == "loaded":
                continue
            base = Path(manifest_path).parent
            manifest = json.loads(Path(manifest_path).read_text())
            table = _read_committed_bronze(base, manifest, batch_id)
            n = 0
            if table.num_rows:
                for row in table.to_pylist():
                    cur.execute(
                        """INSERT INTO raw_stage.order_items (
                           order_id, order_item_id, source_cursor_key, product_id, seller_id,
                           shipping_limit_at, shipping_limit_at_source_text, shipping_limit_at_timezone_resolution,
                           price, freight_value, source_created_at, source_updated_at, payload_hash, batch_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (order_id, order_item_id, source_updated_at) DO NOTHING""",
                        (
                            row.get("order_id"),
                            row.get("order_item_id"),
                            row.get("source_cursor_key"),
                            row.get("product_id"),
                            row.get("seller_id"),
                            row.get("shipping_limit_at"),
                            row.get("shipping_limit_at_source_text"),
                            row.get("shipping_limit_at_timezone_resolution"),
                            row.get("price"),
                            row.get("freight_value"),
                            row.get("source_created_at") or row.get("source_updated_at"),
                            row.get("source_updated_at"),
                            row.get("payload_hash"),
                            batch_id,
                        ),
                    )
                    n += 1
            cur.execute(
                """INSERT INTO control.batch_load (batch_id, target_schema, target_table, status, loaded_rows)
                   VALUES (%s,'raw_stage','order_items','loaded',%s)
                   ON CONFLICT (batch_id, target_schema, target_table) DO UPDATE SET status='loaded', loaded_rows=%s""",
                (batch_id, n, n),
            )
        wconn.commit()
    print("load ok")


if __name__ == "__main__":
    main()
