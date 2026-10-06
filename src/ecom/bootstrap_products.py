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
from .contracts import PRODUCT_BOOTSTRAP_CONTRACT_PATH, load_contract, schema_by_name
from .db import connect

_INT_COLUMNS = (
    "product_name_lenght",
    "product_description_lenght",
    "product_photos_qty",
    "product_weight_g",
    "product_length_cm",
    "product_height_cm",
    "product_width_cm",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist products bootstrap")
    p.add_argument("--csv", default="dataset/olist_products_dataset.csv")
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
        manifest_path = PRODUCT_BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
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


def _parse_optional_int(value: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env()
    attempt_id = args.attempt_id or f"boot-products-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(PRODUCT_BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
    product_id_re = re.compile(fields["product_id"]["pattern"])
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
    duplicate_accepted_product_id = False
    for r in rows:
        violations: list[str] = []
        pid = r["product_id"]
        if not pid or not product_id_re.match(pid):
            violations.append("OLIST-PROD-KEY-001")
        if pid in seen and pid and product_id_re.match(pid):
            violations.append("OLIST-PROD-KEY-002")
            duplicate_accepted_product_id = True
        if pid and product_id_re.match(pid):
            seen.add(pid)
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "product_id": pid,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append(
            {
                "raw": r,
                "ints": {col: _parse_optional_int(r[col]) for col in _INT_COLUMNS},
            }
        )

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    qdir = settings.data_dir / "quarantine" / "bootstrap" / "products" / f"attempt_id={attempt_id}"
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_product_id:
        raise SystemExit("bootstrap blocking failure: duplicate accepted product_id")

    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r, ints = a["raw"], a["ints"]
                cur.execute(
                    """INSERT INTO source.products (
                      product_id, product_category_name,
                      product_name_lenght, product_description_lenght, product_photos_qty,
                      product_weight_g, product_length_cm, product_height_cm, product_width_cm,
                      source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (product_id) DO NOTHING""",
                    (
                        r["product_id"],
                        r["product_category_name"] or None,
                        ints["product_name_lenght"],
                        ints["product_description_lenght"],
                        ints["product_photos_qty"],
                        ints["product_weight_g"],
                        ints["product_length_cm"],
                        ints["product_height_cm"],
                        ints["product_width_cm"],
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
