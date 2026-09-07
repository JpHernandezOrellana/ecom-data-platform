from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .config import Settings
from .contracts import ALLOWED_STATUSES, EXPECTED_BOOTSTRAP_HEADER
from .db import connect
from .timez import localize_source

ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist orders bootstrap")
    p.add_argument("--csv", default="dataset/olist_orders_dataset.csv")
    p.add_argument("--attempt-id", default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env()
    attempt_id = args.attempt_id or f"boot-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    bootstrap_ts = datetime.fromisoformat(settings.bootstrap_loaded_at)
    if bootstrap_ts.tzinfo is None:
        bootstrap_ts = bootstrap_ts.replace(tzinfo=UTC)

    with csv_path.open(encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        if reader.fieldnames != EXPECTED_BOOTSTRAP_HEADER:
            raise SystemExit(f"bootstrap structural failure: unexpected header {reader.fieldnames}")
        rows = list(reader)

    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        violations: list[str] = []
        oid, st = r["order_id"], r["order_status"]
        if not oid or not ID_RE.match(oid):
            violations.append("OLIST-ORD-KEY-001")
        if oid in seen:
            violations.append("OLIST-ORD-KEY-002")
        if st not in ALLOWED_STATUSES:
            violations.append("OLIST-ORD-STATUS-001")
        loc: dict[str, tuple] = {}
        for col in [
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ]:
            required = col in ("order_purchase_timestamp", "order_estimated_delivery_date")
            val = r[col]
            if (val is None or val == "") and required:
                violations.append("OLIST-ORD-TIME-001")
                continue
            if val in (None, ""):
                loc[col] = (None, None)
                continue
            try:
                utc_dt, code = localize_source(val)
                # Store under both CSV name and operational name for mapping
                loc[col] = (utc_dt, code)
                op = (
                    col.replace("order_delivered_carrier_date", "order_delivered_carrier_at")
                    .replace("order_delivered_customer_date", "order_delivered_customer_at")
                    .replace("order_purchase_timestamp", "order_purchase_at")
                    .replace("order_estimated_delivery_date", "order_estimated_delivery_at")
                )
                loc[op] = (utc_dt, code)
            except ValueError:
                violations.append("OLIST-ORD-TIME-001")
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "order_id": oid,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": "1.0.0",
                }
            )
            continue
        seen.add(oid)
        accepted.append({"raw": r, "loc": loc})

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    # Durably preserve bootstrap quarantine
    qdir = settings.data_dir / "quarantine" / "bootstrap" / "orders" / f"attempt_id={attempt_id}"
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    if len(rejected) > 10 or rate > 0.01:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")

    # Insert accepted into source.orders
    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r, loc = a["raw"], a["loc"]
                cur.execute(
                    """INSERT INTO source.orders (
                      order_id, customer_id, order_status,
                      order_purchase_at, order_purchase_at_source_text, order_purchase_at_timezone_resolution,
                      order_approved_at, order_approved_at_source_text, order_approved_at_timezone_resolution,
                      order_delivered_carrier_at, order_delivered_carrier_at_source_text, order_delivered_carrier_at_timezone_resolution,
                      order_delivered_customer_at, order_delivered_customer_at_source_text, order_delivered_customer_at_timezone_resolution,
                      order_estimated_delivery_at, order_estimated_delivery_at_source_text, order_estimated_delivery_at_timezone_resolution,
                      source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (order_id) DO NOTHING""",
                    (
                        r["order_id"],
                        r["customer_id"],
                        r["order_status"],
                        loc["order_purchase_timestamp"][0],
                        r["order_purchase_timestamp"],
                        loc["order_purchase_timestamp"][1],
                        loc["order_approved_at"][0],
                        r["order_approved_at"] or None,
                        loc["order_approved_at"][1],
                        loc["order_delivered_carrier_date"][0],
                        r["order_delivered_carrier_date"] or None,
                        loc["order_delivered_carrier_date"][1],
                        loc["order_delivered_customer_date"][0],
                        r["order_delivered_customer_date"] or None,
                        loc["order_delivered_customer_date"][1],
                        loc["order_estimated_delivery_at"][0],
                        r["order_estimated_delivery_date"],
                        loc["order_estimated_delivery_at"][1],
                        bootstrap_ts,
                        bootstrap_ts,
                    ),
                )
        conn.commit()
    print(f"bootstrap ok: accepted={len(accepted)} rejected={len(rejected)} attempt={attempt_id}")


def _source_writer_dsn(settings: Settings) -> str:
    import os

    return os.environ.get("SOURCE_DSN", settings.source_dsn)


if __name__ == "__main__":
    main()
