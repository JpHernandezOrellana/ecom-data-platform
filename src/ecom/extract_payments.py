from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .batchid import compute_batch_id, compute_quarantine_id
from .config import Settings
from .contracts import PAYMENT_OPERATIONAL_CONTRACT_PATH, load_contract, schema_by_name
from .cursor import build_predicate
from .db import connect, ensure_phase_1_1_warehouse_schema, ensure_phase_2b_warehouse_schema
from .extract import _fmt_cursor, _sha256_file, _verify_manifest_files

ID_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCE_NAME = "source_postgres"
ENTITY = "order_payments"


def _validate_operational_row(row: dict, contract: dict) -> list[str]:
    fields = schema_by_name(contract)
    codes: list[str] = []
    for name, field in fields.items():
        if field.get("source") == "generated_column":
            continue
        value = row[name]
        if field["required"] and value is None:
            codes.append("OP-PAY-REQUIRED-001")
        if value is not None and "pattern" in field and not re.fullmatch(field["pattern"], value):
            codes.append("OP-PAY-KEY-001")
        if value is not None and "allowed_values" in field and value not in field["allowed_values"]:
            codes.append("OP-PAY-TYPE-001")
    if row["payment_value"] is None or row["payment_value"] < 0:
        codes.append("OP-PAY-MONEY-001")
    return sorted(set(codes))


def main() -> None:
    p = argparse.ArgumentParser(description="Bounded incremental order_payments extraction")
    p.add_argument("--run-mode", default="incremental", choices=["incremental", "backfill"])
    p.add_argument("--backfill-request-id", default="")
    p.add_argument("--backfill-from-ts", default="")
    p.add_argument("--backfill-from-key", default="")
    p.add_argument("--backfill-to-ts", default="")
    p.add_argument("--backfill-to-key", default="")
    p.add_argument("--backfill-reason", default="")
    p.add_argument(
        "--fail-after-publish",
        action="store_true",
        help="Test hook: crash after rename, before checkpoint",
    )
    args = p.parse_args()
    settings = Settings.from_env()
    if settings.page_size < 1:
        raise SystemExit("BATCH_PAGE_SIZE must be positive")
    contract = load_contract(PAYMENT_OPERATIONAL_CONTRACT_PATH)
    contract_version = contract["contract_version"]
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    attempt_id = f"att-{uuid.uuid4().hex[:8]}"

    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        ensure_phase_1_1_warehouse_schema(wconn)
        ensure_phase_2b_warehouse_schema(wconn)
        cur.execute(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint WHERE source_name=%s AND entity_name=%s",
            (SOURCE_NAME, ENTITY),
        )
        row = cur.fetchone()
        before_ts, before_key = (row[0], row[1]) if row else (None, None)

    is_backfill = args.run_mode == "backfill"
    if is_backfill and not args.backfill_request_id:
        raise SystemExit("backfill mode requires --backfill-request-id")
    if bool(args.backfill_from_ts) != bool(args.backfill_from_key):
        raise SystemExit("backfill --backfill-from-ts and --backfill-from-key go together")
    if bool(args.backfill_to_ts) != bool(args.backfill_to_key):
        raise SystemExit("backfill --backfill-to-ts and --backfill-to-key go together")
    if is_backfill:
        lower_ts, lower_key, upper_ts, upper_key = _prepare_backfill_request(settings, args)
        has_lower = True
    else:
        recovered = _try_recover(settings, before_ts, before_key)
        if recovered:
            print(f"recovered committed batch {recovered} without re-extraction")
            return
        lower_ts, lower_key = before_ts, before_key
        upper_ts = upper_key = None
        has_lower = before_ts is not None

    accepted: list[dict] = []
    rejected: list[dict] = []
    seen_versions: dict[tuple, str] = {}
    with connect(settings.source_dsn, retries=3) as sconn:
        sconn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with sconn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM source.order_payments "
                "WHERE source_updated_at IS NULL OR order_id IS NULL OR payment_sequential IS NULL"
            )
            (nulls,) = cur.fetchone()  # type: ignore
            if nulls:
                raise SystemExit(f"extraction blocking failure: {nulls} null cursor components")
            if not is_backfill:
                cur.execute(
                    "SELECT source_updated_at, source_cursor_key FROM source.order_payments "
                    "ORDER BY source_updated_at DESC, source_cursor_key DESC LIMIT 1"
                )
                top = cur.fetchone()
                if top is None:
                    print("no_op: source empty")
                    return
                upper_ts, upper_key = top
            assert upper_ts is not None and upper_key is not None
            params = {"upper_ts": upper_ts, "upper_key": upper_key}
            if has_lower:
                params.update({"before_ts": lower_ts, "before_key": lower_key})
            if has_lower and (upper_ts, upper_key) <= (lower_ts, lower_key):  # type: ignore
                print("no_op: empty window")
                return
            sql = (
                "SELECT order_id, payment_sequential, source_cursor_key, payment_type, "
                "payment_installments, payment_value, source_created_at, source_updated_at "
                f"FROM source.order_payments {build_predicate(has_lower, 'source_cursor_key')}"
            )
            with sconn.cursor(name="payments_extract") as page_cursor:
                page_cursor.execute(sql, params)
                cols = [description.name for description in page_cursor.description]
                while page := page_cursor.fetchmany(settings.page_size):
                    for values in page:
                        r = dict(zip(cols, values))
                        codes = _validate_operational_row(r, contract)
                        payload = json.dumps({k: str(v) for k, v in r.items()}, sort_keys=True)
                        phash = hashlib.sha256(payload.encode()).hexdigest()
                        ver = (r["order_id"], r["payment_sequential"], str(r["source_updated_at"]))
                        if ver in seen_versions and seen_versions[ver] != phash:
                            raise SystemExit(
                                "extraction blocking failure: conflicting payload for one source version"
                            )
                        seen_versions.setdefault(ver, phash)
                        if codes:
                            rejected.append(
                                {
                                    "quarantine_id": compute_quarantine_id(
                                        ENTITY, phash, contract_version, codes
                                    ),
                                    "run_id": run_id,
                                    "attempt_id": attempt_id,
                                    "order_id": r["order_id"],
                                    "payment_sequential": r["payment_sequential"],
                                    "original_payload": payload,
                                    "payload_hash": phash,
                                    "violation_codes": codes,
                                    "contract_version": contract_version,
                                }
                            )
                        else:
                            out = {
                                k: (v.isoformat() if isinstance(v, datetime) else v)
                                for k, v in r.items()
                            }
                            out["payment_value"] = str(out["payment_value"])
                            out["payload_hash"] = phash
                            out["batch_run_id"] = run_id
                            accepted.append(out)

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    cursor_before_s = _fmt_cursor(lower_ts, lower_key)
    cursor_upper_s = _fmt_cursor(upper_ts, upper_key)
    batch_id = compute_batch_id(
        source=SOURCE_NAME,
        entity=ENTITY,
        cursor_before=cursor_before_s,
        cursor_upper=cursor_upper_s,
        contract_version=contract_version,
        run_mode=args.run_mode,
        backfill_request_id=args.backfill_request_id,
    )
    if len(rejected) > 10 or rate > 0.01:
        fdir = (
            settings.data_dir
            / "quarantine"
            / "extraction"
            / "order_payments"
            / f"attempt_id={attempt_id}"
        )
        fdir.mkdir(parents=True, exist_ok=True)
        if rejected:
            pq.write_table(pa.Table.from_pylist(rejected), fdir / "rejected.parquet")
        raise SystemExit(f"extraction rejected threshold exceeded: {len(rejected)}/{evaluated}")

    upper_date = upper_ts.astimezone(UTC).date().isoformat()
    committed = (
        settings.data_dir
        / "committed_batches"
        / "order_payments"
        / f"cursor_upper_date={upper_date}"
        / f"batch_id={batch_id}"
    )
    tmp = settings.data_dir / "committed_batches_tmp" / batch_id
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "bronze").mkdir(parents=True, exist_ok=True)
    (tmp / "quarantine").mkdir(parents=True, exist_ok=True)
    if accepted:
        pq.write_table(pa.Table.from_pylist(accepted), tmp / "bronze" / "accepted.parquet")
    else:
        pq.write_table(
            pa.Table.from_pylist([], schema=pa.schema([])), tmp / "bronze" / "accepted.parquet"
        )
    if rejected:
        pq.write_table(pa.Table.from_pylist(rejected), tmp / "quarantine" / "rejected.parquet")
    manifest = {
        "batch_id": batch_id,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "source": SOURCE_NAME,
        "entity": ENTITY,
        "run_mode": args.run_mode,
        "cursor_before": cursor_before_s,
        "cursor_upper": cursor_upper_s,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "contract_version": contract_version,
    }
    files: dict[str, str] = {
        "bronze/accepted.parquet": _sha256_file(tmp / "bronze" / "accepted.parquet")
    }
    if rejected:
        files["quarantine/rejected.parquet"] = _sha256_file(tmp / "quarantine" / "rejected.parquet")
    manifest["files"] = files
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    committed.parent.mkdir(parents=True, exist_ok=True)
    if committed.exists():
        disk_manifest = json.loads((committed / "manifest.json").read_text())
        _verify_manifest_files(committed, disk_manifest)
        shutil.rmtree(tmp)
        manifest = disk_manifest
        run_id = manifest["run_id"]
    else:
        tmp.rename(committed)

    if args.fail_after_publish:
        raise SystemExit("injected crash after filesystem publication, before checkpoint commit")

    if is_backfill:
        _register_backfill_batch(
            settings, manifest, str(committed / "manifest.json"), run_id, args.backfill_request_id
        )
    else:
        _commit_checkpoint(
            settings,
            manifest,
            str(committed / "manifest.json"),
            run_id,
            before_ts,
            before_key,
            upper_ts,
            upper_key,
        )
    print(f"extraction ok: batch={batch_id} accepted={len(accepted)} rejected={len(rejected)}")


def _try_recover(settings: Settings, before_ts, before_key) -> str | None:
    base = settings.data_dir / "committed_batches" / "order_payments"
    if not base.exists():
        return None
    want = _fmt_cursor(before_ts, before_key)
    for manifest_path in sorted(base.glob("*/batch_id=*/manifest.json")):
        try:
            m = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("cursor_before") != want or m.get("run_mode", "incremental") != "incremental":
            continue
        with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM control.batch WHERE batch_id=%s AND status='committed'",
                (m["batch_id"],),
            )
            if cur.fetchone():
                continue
        upper_ts = datetime.fromisoformat(m["cursor_upper"].split("|")[0])
        upper_key = m["cursor_upper"].split("|")[1]
        _verify_manifest_files(manifest_path.parent, m)
        _commit_checkpoint(
            settings, m, str(manifest_path), m["run_id"], before_ts, before_key, upper_ts, upper_key
        )
        return m["batch_id"]
    return None


def _insert_batch(cur, manifest: dict, manifest_path: str, run_id: str) -> None:
    cur.execute(
        """INSERT INTO control.batch (batch_id, source_name, entity_name, run_id, run_mode,
           cursor_before_updated_at, cursor_before_key, cursor_upper_updated_at, cursor_upper_key,
           contract_version, manifest_path, accepted_count, rejected_count, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'committed')
           ON CONFLICT (batch_id) DO NOTHING""",
        (
            manifest["batch_id"],
            SOURCE_NAME,
            ENTITY,
            run_id,
            manifest.get("run_mode", "incremental"),
            _parse_cursor_ts(manifest["cursor_before"]),
            _parse_cursor_key(manifest["cursor_before"]),
            _parse_cursor_ts(manifest["cursor_upper"]),
            _parse_cursor_key(manifest["cursor_upper"]),
            manifest["contract_version"],
            manifest_path,
            manifest["accepted_count"],
            manifest["rejected_count"],
        ),
    )


def _parse_cursor_ts(cursor_s: str):
    if cursor_s == "NONE":
        return None
    return datetime.fromisoformat(cursor_s.split("|")[0])


def _parse_cursor_key(cursor_s: str):
    if cursor_s == "NONE":
        return None
    return cursor_s.split("|")[1]


def _prepare_backfill_request(
    settings: Settings, args: argparse.Namespace
) -> tuple[datetime, str, datetime, str]:
    """Create or resume one bounded, auditable backfill request (ADR-002, extended by ADR-006)."""
    with connect(settings.warehouse_dsn) as conn, conn.cursor() as cur:
        ensure_phase_1_1_warehouse_schema(conn)
        cur.execute(
            """SELECT cursor_from_updated_at, cursor_from_key, cursor_to_updated_at, cursor_to_key
               FROM control.backfill_request WHERE request_id=%s AND source_name=%s AND entity_name=%s""",
            (args.backfill_request_id, SOURCE_NAME, ENTITY),
        )
        existing = cur.fetchone()
        if existing:
            stored_from_ts, stored_from_key, stored_to_ts, stored_to_key = existing
            supplied = (
                args.backfill_from_ts,
                args.backfill_from_key,
                args.backfill_to_ts,
                args.backfill_to_key,
            )
            stored = (
                stored_from_ts.isoformat(),
                stored_from_key,
                stored_to_ts.isoformat(),
                stored_to_key,
            )
            if any(supplied) and supplied != stored:
                raise SystemExit("backfill request cursor does not match its registered window")
            return stored_from_ts, stored_from_key, stored_to_ts, stored_to_key

        if not all(
            (
                args.backfill_from_ts,
                args.backfill_from_key,
                args.backfill_to_ts,
                args.backfill_to_key,
                args.backfill_reason,
            )
        ):
            raise SystemExit(
                "new backfill requires --backfill-from-*, --backfill-to-*, and --backfill-reason"
            )
        from_ts = datetime.fromisoformat(args.backfill_from_ts)
        to_ts = datetime.fromisoformat(args.backfill_to_ts)
        if (to_ts, args.backfill_to_key) <= (from_ts, args.backfill_from_key):
            raise SystemExit("backfill upper cursor must be greater than its lower cursor")
        cur.execute(
            """INSERT INTO control.backfill_request (
                 request_id, source_name, entity_name, cursor_from_updated_at, cursor_from_key,
                 cursor_to_updated_at, cursor_to_key, reason, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')""",
            (
                args.backfill_request_id,
                SOURCE_NAME,
                ENTITY,
                from_ts,
                args.backfill_from_key,
                to_ts,
                args.backfill_to_key,
                args.backfill_reason,
            ),
        )
        conn.commit()
    return from_ts, args.backfill_from_key, to_ts, args.backfill_to_key


def _register_backfill_batch(
    settings: Settings, manifest: dict, manifest_path: str, run_id: str, request_id: str
) -> None:
    """Register backfill evidence and request state without moving the normal checkpoint."""
    _verify_manifest_files(Path(manifest_path).parent, manifest)
    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        _insert_batch(cur, manifest, manifest_path, run_id)
        cur.execute(
            """UPDATE control.backfill_request
               SET batch_id=%s, status='committed', completed_at=now()
               WHERE request_id=%s AND source_name=%s AND entity_name=%s""",
            (manifest["batch_id"], request_id, SOURCE_NAME, ENTITY),
        )
        if cur.rowcount != 1:
            wconn.rollback()
            raise SystemExit("backfill request was not registered")
        wconn.commit()


def _commit_checkpoint(
    settings, manifest, manifest_path, run_id, before_ts, before_key, upper_ts, upper_key
) -> None:
    _verify_manifest_files(Path(manifest_path).parent, manifest)
    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        cur.execute(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint WHERE source_name=%s AND entity_name=%s",
            (SOURCE_NAME, ENTITY),
        )
        cur_row = cur.fetchone()
        cur_ts, cur_key = (cur_row[0], cur_row[1]) if cur_row else (None, None)
        if (cur_ts, cur_key) != (before_ts, before_key):
            wconn.rollback()
            raise SystemExit("checkpoint compare-and-swap conflict: concurrent committer")
        _insert_batch(cur, manifest, manifest_path, run_id)
        cur.execute(
            """INSERT INTO control.checkpoint (source_name, entity_name, cursor_updated_at, cursor_key,
               last_committed_batch_id, last_ingestion_run_id, committed_at, checkpoint_version)
               VALUES (%s,%s,%s,%s,%s,%s,now(),1)
               ON CONFLICT (source_name, entity_name) DO UPDATE SET
                 cursor_updated_at=EXCLUDED.cursor_updated_at, cursor_key=EXCLUDED.cursor_key,
                 last_committed_batch_id=EXCLUDED.last_committed_batch_id,
                 last_ingestion_run_id=EXCLUDED.last_ingestion_run_id,
                 committed_at=now(), checkpoint_version=control.checkpoint.checkpoint_version+1""",
            (SOURCE_NAME, ENTITY, upper_ts, upper_key, manifest["batch_id"], run_id),
        )
        wconn.commit()


if __name__ == "__main__":
    main()
