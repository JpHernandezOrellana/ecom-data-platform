from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import uuid
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from .batchid import compute_batch_id, compute_quarantine_id
from .config import Settings
from .contracts import ALLOWED_STATUSES
from .cursor import build_predicate
from .db import connect

ID_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCE_NAME = "source_postgres"
ENTITY = "orders"


def _fmt_cursor(ts: datetime | None, key: str | None) -> str:
    if ts is None:
        return "NONE"
    return f"{ts.isoformat()}|{key}"


def main() -> None:
    p = argparse.ArgumentParser(description="Bounded incremental orders extraction")
    p.add_argument("--run-mode", default="incremental", choices=["incremental", "backfill"])
    p.add_argument("--backfill-request-id", default="")
    p.add_argument(
        "--fail-after-publish",
        action="store_true",
        help="Test hook: crash after rename, before checkpoint",
    )
    args = p.parse_args()
    settings = Settings.from_env()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    attempt_id = f"att-{uuid.uuid4().hex[:8]}"

    with connect(settings.warehouse_dsn) as wconn, wconn.cursor() as cur:
        cur.execute(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint WHERE source_name=%s AND entity_name=%s",
            (SOURCE_NAME, ENTITY),
        )
        row = cur.fetchone()
        before_ts, before_key = (row[0], row[1]) if row else (None, None)

    # Recovery: committed manifest matching current checkpoint but not registered
    recovered = _try_recover(settings, before_ts, before_key)
    if recovered:
        print(f"recovered committed batch {recovered} without re-extraction")
        return

    with connect(settings.source_dsn) as sconn:
        sconn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with sconn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM source.orders WHERE source_updated_at IS NULL OR order_id IS NULL"
            )
            (nulls,) = cur.fetchone()  # type: ignore
            if nulls:
                raise SystemExit(f"extraction blocking failure: {nulls} null cursor components")
            cur.execute(
                "SELECT source_updated_at, order_id FROM source.orders ORDER BY source_updated_at DESC, order_id DESC LIMIT 1"
            )
            top = cur.fetchone()
            if top is None:
                print("no_op: source empty")
                return
            upper_ts, upper_key = top
            params = {"upper_ts": upper_ts, "upper_key": upper_key}
            has_lower = before_ts is not None
            if has_lower:
                params.update({"before_ts": before_ts, "before_key": before_key})
            # empty-window check
            if has_lower and (upper_ts, upper_key) <= (before_ts, before_key):  # type: ignore
                print("no_op: empty window")
                return
            sql = (
                "SELECT order_id, customer_id, order_status, order_purchase_at, "
                "order_approved_at, order_delivered_carrier_at, order_delivered_customer_at, "
                "order_estimated_delivery_at, source_created_at, source_updated_at "
                f"FROM source.orders {build_predicate(has_lower)}"
            )
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            extracted = [dict(zip(cols, r)) for r in cur.fetchall()]

    accepted: list[dict] = []
    rejected: list[dict] = []
    seen_versions: dict[tuple, str] = {}
    for r in extracted:
        codes: list[str] = []
        if not r["order_id"] or not ID_RE.match(r["order_id"]):
            codes.append("OP-ORD-KEY-001")
        if r["order_status"] not in ALLOWED_STATUSES:
            codes.append("OP-ORD-STATUS-001")
        payload = json.dumps({k: str(v) for k, v in r.items()}, sort_keys=True)
        phash = hashlib.sha256(payload.encode()).hexdigest()
        ver = (r["order_id"], str(r["source_updated_at"]))
        if ver in seen_versions and seen_versions[ver] != phash:
            raise SystemExit(
                "extraction blocking failure: conflicting payload for one source version"
            )
        seen_versions.setdefault(ver, phash)
        if codes:
            rejected.append(
                {
                    "quarantine_id": compute_quarantine_id(ENTITY, phash, "1.0.0", codes),
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "order_id": r["order_id"],
                    "original_payload": payload,
                    "payload_hash": phash,
                    "violation_codes": codes,
                    "contract_version": "1.0.0",
                }
            )
        else:
            out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
            out["payload_hash"] = phash
            out["batch_run_id"] = run_id
            accepted.append(out)

    evaluated = len(accepted) + len(rejected)
    rate = (len(rejected) / evaluated) if evaluated else 0.0
    cursor_before_s = _fmt_cursor(before_ts, before_key)
    cursor_upper_s = _fmt_cursor(upper_ts, upper_key)
    batch_id = compute_batch_id(
        source=SOURCE_NAME,
        entity=ENTITY,
        cursor_before=cursor_before_s,
        cursor_upper=cursor_upper_s,
        contract_version="1.0.0",
        run_mode=args.run_mode,
        backfill_request_id=args.backfill_request_id,
    )
    if len(rejected) > 10 or rate > 0.01:
        # durable failed-attempt evidence, no committed batch, no checkpoint
        fdir = (
            settings.data_dir / "quarantine" / "extraction" / "orders" / f"attempt_id={attempt_id}"
        )
        fdir.mkdir(parents=True, exist_ok=True)
        if rejected:
            pq.write_table(pa.Table.from_pylist(rejected), fdir / "rejected.parquet")
        raise SystemExit(f"extraction rejected threshold exceeded: {len(rejected)}/{evaluated}")

    upper_date = upper_ts.astimezone(UTC).date().isoformat()
    committed = (
        settings.data_dir
        / "committed_batches"
        / "orders"
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
        "contract_version": "1.0.0",
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    committed.parent.mkdir(parents=True, exist_ok=True)
    if committed.exists():
        shutil.rmtree(tmp)
    else:
        tmp.rename(committed)

    if args.fail_after_publish:
        raise SystemExit("injected crash after filesystem publication, before checkpoint commit")

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
    base = settings.data_dir / "committed_batches" / "orders"
    if not base.exists():
        return None
    want = _fmt_cursor(before_ts, before_key)
    for manifest_path in sorted(base.glob("*/batch_id=*/manifest.json")):
        try:
            m = json.loads(manifest_path.read_text())
        except (
            OSError,
            json.JSONDecodeError,
        ):  # corrupt/incomplete attempt is not recoverable state
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
        _commit_checkpoint(
            settings, m, str(manifest_path), m["run_id"], before_ts, before_key, upper_ts, upper_key
        )
        return m["batch_id"]
    return None


def _commit_checkpoint(
    settings, manifest, manifest_path, run_id, before_ts, before_key, upper_ts, upper_key
) -> None:
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
                before_ts,
                before_key,
                upper_ts,
                upper_key,
                "1.0.0",
                manifest_path,
                manifest["accepted_count"],
                manifest["rejected_count"],
            ),
        )
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
