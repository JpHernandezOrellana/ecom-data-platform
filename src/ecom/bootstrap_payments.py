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
from .contracts import PAYMENT_BOOTSTRAP_CONTRACT_PATH, load_contract, schema_by_name
from .db import connect


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic Olist order_payments bootstrap")
    p.add_argument("--csv", default="dataset/olist_order_payments_dataset.csv")
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
        manifest_path = PAYMENT_BOOTSTRAP_CONTRACT_PATH.parents[2] / manifest_path
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
    attempt_id = args.attempt_id or f"boot-pay-{uuid.uuid4().hex[:12]}"
    csv_path = Path(args.csv)
    contract = load_contract(PAYMENT_BOOTSTRAP_CONTRACT_PATH)
    fields = schema_by_name(contract)
    expected_header = [field["name"] for field in contract["schema"]]
    order_id_re = re.compile(fields["order_id"]["pattern"])
    allowed_types = set(fields["payment_type"]["allowed_values"])
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
        oid, seq_raw = r["order_id"], r["payment_sequential"]
        if not oid or not order_id_re.match(oid):
            violations.append("OLIST-PAY-KEY-001")
        try:
            seq = int(seq_raw)
            if seq < 1:
                raise ValueError
        except (TypeError, ValueError):
            seq = None
            violations.append("OLIST-PAY-SEQ-001")
        key = (oid, seq_raw)
        if key in seen:
            violations.append("OLIST-PAY-KEY-002")
            duplicate_accepted_key = True
        else:
            seen.add(key)
        if r["payment_type"] not in allowed_types:
            violations.append("OLIST-PAY-TYPE-001")
        try:
            installments = int(r["payment_installments"])
            if installments < 0:
                raise ValueError
        except (TypeError, ValueError):
            installments = None
            violations.append("OLIST-PAY-MONEY-001")
        value = _parse_money(r["payment_value"])
        if value is None:
            violations.append("OLIST-PAY-MONEY-001")
        if violations:
            payload = json.dumps(r, sort_keys=True)
            rejected.append(
                {
                    "quarantine_id": hashlib.sha256(payload.encode()).hexdigest()[:32],
                    "attempt_id": attempt_id,
                    "order_id": oid,
                    "payment_sequential": seq_raw,
                    "original_payload": payload,
                    "violation_codes": violations,
                    "contract_version": contract_version,
                }
            )
            continue
        accepted.append(
            {
                "raw": r,
                "payment_sequential": seq,
                "payment_installments": installments,
                "payment_value": value,
            }
        )

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    qdir = (
        settings.data_dir
        / "quarantine"
        / "bootstrap"
        / "order_payments"
        / f"attempt_id={attempt_id}"
    )
    qdir.mkdir(parents=True, exist_ok=True)
    if rejected:
        table = pa.Table.from_pylist(rejected)
        pq.write_table(table, qdir / "rejected.parquet")
    policy = contract["rejection_policy"]
    if len(rejected) > policy["maximum_rejected_rows"] or rate > policy["maximum_rejected_rate"]:
        raise SystemExit(f"bootstrap rejected threshold exceeded: {len(rejected)}/{evaluated}")
    if duplicate_accepted_key:
        raise SystemExit(
            "bootstrap blocking failure: duplicate accepted (order_id, payment_sequential)"
        )

    with connect(_source_writer_dsn(settings)) as conn:
        with conn.cursor() as cur:
            for a in accepted:
                r = a["raw"]
                cur.execute(
                    """INSERT INTO source.order_payments (
                      order_id, payment_sequential, payment_type, payment_installments,
                      payment_value, source_created_at, source_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (order_id, payment_sequential) DO NOTHING""",
                    (
                        r["order_id"],
                        a["payment_sequential"],
                        r["payment_type"],
                        a["payment_installments"],
                        a["payment_value"],
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
