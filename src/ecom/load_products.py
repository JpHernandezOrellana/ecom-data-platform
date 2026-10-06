from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from .config import Settings
from .db import (
    connect,
    ensure_phase_1_1_warehouse_schema,
    ensure_phase_2c_products_warehouse_schema,
)
from .extract import _verify_manifest_files


def main() -> None:
    p = argparse.ArgumentParser(description="Idempotent Bronze -> raw_stage load for products")
    p.parse_args()
    settings = Settings.from_env()
    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        ensure_phase_1_1_warehouse_schema(wconn)
        ensure_phase_2c_products_warehouse_schema(wconn)
        cur.execute(
            "SELECT batch_id, manifest_path FROM control.batch WHERE status='committed' AND entity_name='products'"
        )
        batches = cur.fetchall()
        for batch_id, manifest_path in batches:
            cur.execute(
                "SELECT status FROM control.batch_load WHERE batch_id=%s AND target_schema='raw_stage' AND target_table='products'",
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
                        """INSERT INTO raw_stage.products (
                           product_id, product_category_name,
                           product_name_lenght, product_description_lenght, product_photos_qty,
                           product_weight_g, product_length_cm, product_height_cm, product_width_cm,
                           source_created_at, source_updated_at, payload_hash, batch_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (product_id, source_updated_at) DO NOTHING""",
                        (
                            row.get("product_id"),
                            row.get("product_category_name"),
                            row.get("product_name_lenght"),
                            row.get("product_description_lenght"),
                            row.get("product_photos_qty"),
                            row.get("product_weight_g"),
                            row.get("product_length_cm"),
                            row.get("product_height_cm"),
                            row.get("product_width_cm"),
                            row.get("source_created_at") or row.get("source_updated_at"),
                            row.get("source_updated_at"),
                            row.get("payload_hash"),
                            batch_id,
                        ),
                    )
                    n += 1
            cur.execute(
                """INSERT INTO control.batch_load (batch_id, target_schema, target_table, status, loaded_rows)
                   VALUES (%s,'raw_stage','products','loaded',%s)
                   ON CONFLICT (batch_id, target_schema, target_table) DO UPDATE SET status='loaded', loaded_rows=%s""",
                (batch_id, n, n),
            )
        wconn.commit()
    print("load ok")


def _read_committed_bronze(base: Path, manifest: dict, batch_id: str):
    _verify_manifest_files(base, manifest)
    table = pq.read_table(base / "bronze" / "accepted.parquet")
    if table.num_rows != manifest["accepted_count"]:
        raise SystemExit(f"load failure: Bronze row count mismatch for committed batch {batch_id}")
    return table


if __name__ == "__main__":
    main()
