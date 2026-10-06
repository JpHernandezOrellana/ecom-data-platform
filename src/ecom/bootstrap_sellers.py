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
from .contracts import SELLER_BOOTSTRAP_CONTRACT_PATH, load_contract, schema_by_name
from .db import connect


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist sellers bootstrap")
    p.add_argument("--csv", default="dataset/olist_sellers_dataset.csv")
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
        manifest_path = SELLER_BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
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
    attempt_id = args.attempt_id or f"boot-sellers-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(SELLER_BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
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
    seen: set[str] = set()
    duplicate_accepted_seller_id = False
    for r in rows:
        violations: list[str] = []
        sid = r["seller_id"]
        if not sid or not seller_id_re.match(sid):
            violations.append("OLIST-SELL-KEY-001")
        if not r["seller_zip_code_prefix"] or not r["seller_city"] or not r["seller_state"]:
            violations.append("OLIST-SELL-KEY-001")
        if sid in seen and sid and seller_id_re.match(sid):
            violations.append("OLIST-SELL-KEY-002")
            duplicate_accepted_seller_id = True
        if sid and seller_id_re.match(sid):
            seen.add(sid)
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "seller_id": sid,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append({"raw": r})

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    qdir = settings.data_dir / "quarantine" / "bootstrap" / "sellers" / f"attempt_id={attempt_id}"
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_seller_id:
        raise SystemExit("bootstrap blocking failure: duplicate accepted seller_id")

    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r = a["raw"]
                cur.execute(
                    """INSERT INTO source.sellers (
                      seller_id, seller_zip_code_prefix, seller_city, seller_state,
                      source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (seller_id) DO NOTHING""",
                    (
                        r["seller_id"],
                        r["seller_zip_code_prefix"],
                        r["seller_city"],
                        r["seller_state"],
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
