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

from .bootstrap import _sha256_file
from .config import Settings
from .contracts import CUSTOMER_BOOTSTRAP_CONTRACT_PATH, load_contract, schema_by_name
from .db import connect


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist customers bootstrap")
    p.add_argument("--csv", default="dataset/olist_customers_dataset.csv")
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
        manifest_path = CUSTOMER_BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
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
    attempt_id = args.attempt_id or f"boot-customers-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(CUSTOMER_BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
    customer_id_re = re.compile(fields["customer_id"]["pattern"])
    customer_unique_id_re = re.compile(fields["customer_unique_id"]["pattern"])
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
    duplicate_accepted_customer_id = False
    for r in rows:
        violations: list[str] = []
        cid = r["customer_id"]
        if not cid or not customer_id_re.match(cid):
            violations.append("OLIST-CUST-KEY-001")
        if not r["customer_unique_id"] or not customer_unique_id_re.match(r["customer_unique_id"]):
            violations.append("OLIST-CUST-KEY-001")
        if not r["customer_zip_code_prefix"] or not r["customer_city"] or not r["customer_state"]:
            violations.append("OLIST-CUST-KEY-001")
        if cid in seen and cid and customer_id_re.match(cid):
            violations.append("OLIST-CUST-KEY-002")
            duplicate_accepted_customer_id = True
        if cid and customer_id_re.match(cid):
            seen.add(cid)
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "customer_id": cid,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append({"raw": r})

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    qdir = settings.data_dir / "quarantine" / "bootstrap" / "customers" / f"attempt_id={attempt_id}"
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_customer_id:
        raise SystemExit("bootstrap blocking failure: duplicate accepted customer_id")

    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r = a["raw"]
                cur.execute(
                    """INSERT INTO source.customers (
                      customer_id, customer_unique_id, customer_zip_code_prefix,
                      customer_city, customer_state, source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (customer_id) DO NOTHING""",
                    (
                        r["customer_id"],
                        r["customer_unique_id"],
                        r["customer_zip_code_prefix"],
                        r["customer_city"],
                        r["customer_state"],
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
