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
from .contracts import BOOTSTRAP_CONTRACT_PATH, accepted_values, load_contract, schema_by_name
from .db import connect
from .timez import localize_source


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist orders bootstrap")
    p.add_argument("--csv", default="dataset/olist_orders_dataset.csv")
    p.add_argument("--attempt-id", default=None)
    p.add_argument(
        "--allow-unverified-input",
        action="store_true",
        help="Allow a synthetic fixture that is intentionally absent from the pinned manifest.",
    )
    return p.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_bootstrap_manifest(csv_path: Path, contract: dict) -> None:
    manifest_path = Path(contract["dataset"]["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
    manifest = json.loads(manifest_path.read_text())
    source_file = contract["dataset"]["source_file"]
    entry = next((item for item in manifest["files"] if item["path"] == source_file), None)
    if entry is None:
        raise SystemExit(f"bootstrap structural failure: manifest has no entry for {source_file}")
    expected_hash = contract["observed_profile"]["source_file_sha256"]
    if entry["sha256"] != expected_hash:
        raise SystemExit("bootstrap structural failure: contract and manifest checksum disagree")
    if _sha256_file(csv_path) != expected_hash:
        raise SystemExit("bootstrap structural failure: input checksum does not match manifest")


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env()
    attempt_id = args.attempt_id or f"boot-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
    allowed_statuses = accepted_values(contract, "order_status")
    order_id_re = re.compile(fields["order_id"]["pattern"])
    customer_id_re = re.compile(fields["customer_id"]["pattern"])
    contract_version = contract["contract_version"]
    if not args.allow_unverified_input:
        _verify_bootstrap_manifest(csv_path, contract)
    bootstrap_ts = datetime.fromisoformat(settings.bootstrap_loaded_at)
    if bootstrap_ts.tzinfo is None:
        bootstrap_ts = bootstrap_ts.replace(tzinfo=UTC)

    with csv_path.open(encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        if reader.fieldnames != expected_header:
            raise SystemExit(f"bootstrap structural failure: unexpected header {reader.fieldnames}")
        rows = list(reader)

    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    duplicate_accepted_order_id = False
    for r in rows:
        violations: list[str] = []
        oid, st = r["order_id"], r["order_status"]
        if not oid or not order_id_re.match(oid):
            violations.append("OLIST-ORD-KEY-001")
        if not r["customer_id"] or not customer_id_re.match(r["customer_id"]):
            violations.append("OLIST-ORD-KEY-001")
        if oid in seen and oid and order_id_re.match(oid):
            violations.append("OLIST-ORD-KEY-002")
            duplicate_accepted_order_id = True
        if oid and order_id_re.match(oid):
            seen.add(oid)
        if st not in allowed_statuses:
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
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append({"raw": r, "loc": loc})

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    # Durably preserve bootstrap quarantine
    qdir = settings.data_dir / "quarantine" / "bootstrap" / "orders" / f"attempt_id={attempt_id}"
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_order_id:
        raise SystemExit("bootstrap blocking failure: duplicate accepted order_id")

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
