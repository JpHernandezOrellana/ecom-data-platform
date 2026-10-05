from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .bootstrap import _sha256_file
from .config import Settings
from .contracts import ITEM_BOOTSTRAP_CONTRACT_PATH, load_contract, schema_by_name
from .db import connect
from .timez import localize_source


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist order_items bootstrap")
    p.add_argument("--csv", default="dataset/olist_order_items_dataset.csv")
    p.add_argument("--attempt-id", default=None)
    p.add_argument(
        "--allow-unverified-input",
        action="store_true",
        help="Allow a synthetic fixture that is intentionally absent from the pinned manifest.",
    )
    return p.parse_args()


def _verify_bootstrap_manifest(csv_path: Path, contract: dict) -> None:
    manifest_path = Path(contract["dataset"]["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = ITEM_BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
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


def _parse_money(value: str) -> Decimal | None:
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None
    if d < 0 or d.as_tuple().exponent < -2:
        return None
    return d


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env()
    attempt_id = args.attempt_id or f"boot-items-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(ITEM_BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
    order_id_re = re.compile(fields["order_id"]["pattern"])
    product_id_re = re.compile(fields["product_id"]["pattern"])
    seller_id_re = re.compile(fields["seller_id"]["pattern"])
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
    seen: set[tuple[str, str]] = set()
    duplicate_accepted_key = False
    for r in rows:
        violations: list[str] = []
        oid, iid_raw = r["order_id"], r["order_item_id"]
        if not oid or not order_id_re.match(oid):
            violations.append("OLIST-ITEM-KEY-001")
        if not r["product_id"] or not product_id_re.match(r["product_id"]):
            violations.append("OLIST-ITEM-KEY-001")
        if not r["seller_id"] or not seller_id_re.match(r["seller_id"]):
            violations.append("OLIST-ITEM-KEY-001")
        try:
            iid = int(iid_raw)
            if iid < 1:
                raise ValueError
        except (TypeError, ValueError):
            iid = None
            violations.append("OLIST-ITEM-SEQ-001")
        key = (oid, iid_raw)
        if key in seen:
            violations.append("OLIST-ITEM-KEY-002")
            duplicate_accepted_key = True
        else:
            seen.add(key)
        price = _parse_money(r["price"])
        if price is None:
            violations.append("OLIST-ITEM-MONEY-001")
        freight = _parse_money(r["freight_value"])
        if freight is None:
            violations.append("OLIST-ITEM-MONEY-001")
        loc_ts = None
        loc_code = None
        val = r["shipping_limit_date"]
        if not val:
            violations.append("OLIST-ITEM-TIME-001")
        else:
            try:
                loc_ts, loc_code = localize_source(val)
            except ValueError:
                violations.append("OLIST-ITEM-TIME-001")
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "order_id": oid,
                    "order_item_id": iid_raw,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append(
            {
                "raw": r,
                "order_item_id": iid,
                "price": price,
                "freight_value": freight,
                "shipping_limit_at": loc_ts,
                "shipping_limit_at_resolution": loc_code,
            }
        )

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    qdir = (
        settings.data_dir / "quarantine" / "bootstrap" / "order_items" / f"attempt_id={attempt_id}"
    )
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_key:
        raise SystemExit("bootstrap blocking failure: duplicate accepted (order_id, order_item_id)")

    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r = a["raw"]
                cur.execute(
                    """INSERT INTO source.order_items (
                      order_id, order_item_id, product_id, seller_id,
                      shipping_limit_at, shipping_limit_at_source_text, shipping_limit_at_timezone_resolution,
                      price, freight_value, source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (order_id, order_item_id) DO NOTHING""",
                    (
                        r["order_id"],
                        a["order_item_id"],
                        r["product_id"],
                        r["seller_id"],
                        a["shipping_limit_at"],
                        r["shipping_limit_date"],
                        a["shipping_limit_at_resolution"],
                        a["price"],
                        a["freight_value"],
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
