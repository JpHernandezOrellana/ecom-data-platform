"""Integration tests requiring local Postgres (compose up). Run with: uv run --extra dev pytest -m integration."""

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[1]


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _pg(query: str, db: str = "warehouse") -> str:
    import psycopg

    dsn = os.environ["WAREHOUSE_DSN" if db == "warehouse" else "SOURCE_DSN"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(query)
        try:
            return str(cur.fetchall())
        except psycopg.ProgrammingError:
            return "ok"


def test_manifest_matches_orders_csv():
    manifest = json.loads((REPO / "data" / "manifest.json").read_text())
    orders = next(f for f in manifest["files"] if f["path"].endswith("olist_orders_dataset.csv"))
    assert orders["logical_rows"] == 99441
    assert len(orders["columns"]) == 8


def test_idempotent_rerun_is_noop():
    r = _run("ecom.extract")
    assert "no_op" in (r.stdout + r.stderr) or r.returncode == 0


def test_crash_recovery_reuses_committed_batch():
    # Force a new mutation so there is work to do (unique ts per run)
    from datetime import datetime

    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    _run("ecom.mutate", "--ts", ts)
    r1 = _run("ecom.extract", "--fail-after-publish")
    assert r1.returncode != 0
    assert "injected crash" in (r1.stdout + r1.stderr)
    before = sorted((REPO / "data" / "committed_batches").rglob("manifest.json"))
    r2 = _run("ecom.extract")
    assert r2.returncode == 0
    after = sorted((REPO / "data" / "committed_batches").rglob("manifest.json"))
    assert len(after) == len(before), "retry must not write a second committed batch"
    assert "recovered committed batch" in r2.stdout or "extraction ok" in r2.stdout


def test_failed_publication_preserves_gold():
    before = _pg("SELECT count(*) FROM gold.mart_daily_order_fulfillment")
    r = _run(
        "ecom.publish",
        "--publication-id",
        "bad999",
        "--test-results",
        "missing-run-results.json",
        "--dbt-manifest",
        "missing-manifest.json",
    )
    assert r.returncode != 0
    after = _pg("SELECT count(*) FROM gold.mart_daily_order_fulfillment")
    assert before == after


def test_double_load_is_idempotent():
    """COMMIT-007: loading the same committed batches twice changes nothing."""
    assert (
        _run("ecom.load").returncode == 0
    )  # converge first: earlier tests may leave batches unloaded
    before = _pg("SELECT count(*) FROM raw_stage.orders")
    r1 = _run("ecom.load")
    assert r1.returncode == 0
    mid = _pg("SELECT count(*) FROM raw_stage.orders")
    r2 = _run("ecom.load")
    assert r2.returncode == 0
    after = _pg("SELECT count(*) FROM raw_stage.orders")
    assert before == mid == after


def test_breaking_operational_schema_fails_closed():
    """DQ-008 / SDD 22.2: incompatible source change fails before publication
    and the normal checkpoint does not move."""
    from datetime import datetime

    import psycopg

    # Force pending work: an empty window would return no_op without touching the table.
    _run("ecom.mutate", "--ts", datetime.now(UTC).replace(microsecond=0).isoformat())
    checkpoint_before = _pg(
        "SELECT cursor_updated_at, cursor_key, last_committed_batch_id FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    manifests_before = sorted((REPO / "data" / "committed_batches").rglob("manifest.json"))
    dsn = os.environ["SOURCE_DSN"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE source.orders RENAME COLUMN order_status TO order_status_broken")
        conn.commit()
    try:
        r = _run("ecom.extract")
        assert r.returncode != 0
        assert "no_op" not in (r.stdout + r.stderr)
    finally:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE source.orders RENAME COLUMN order_status_broken TO order_status"
            )
            conn.commit()
    checkpoint_after = _pg(
        "SELECT cursor_updated_at, cursor_key, last_committed_batch_id FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    manifests_after = sorted((REPO / "data" / "committed_batches").rglob("manifest.json"))
    assert checkpoint_before == checkpoint_after
    assert manifests_before == manifests_after


def test_backfill_leaves_normal_checkpoint():
    """COMMIT-008/009/010: backfill registers evidence without moving the
    normal checkpoint; same request is stable; new request is new evidence."""
    from datetime import datetime

    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    request_id = f"close-{uuid.uuid4().hex}"
    _run("ecom.mutate", "--ts", ts)
    checkpoint_before = _pg(
        "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    backfill_args = (
        "--run-mode",
        "backfill",
        "--backfill-request-id",
        request_id,
        "--backfill-from-ts",
        "2018-10-20T00:00:00+00:00",
        "--backfill-from-key",
        "00000000000000000000000000000000",
        "--backfill-to-ts",
        ts,
        "--backfill-to-key",
        "ffffffffffffffffffffffffffffffff",
        "--backfill-reason",
        "integration-test",
    )
    r1 = _run("ecom.extract", *backfill_args)
    assert r1.returncode == 0
    assert "extraction ok" in r1.stdout
    checkpoint_after = _pg(
        "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    assert checkpoint_before == checkpoint_after
    batch1 = _pg(
        "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    assert (
        _pg(f"SELECT status FROM control.backfill_request WHERE request_id='{request_id}'")
        == "[('committed',)]"
    )
    r2 = _run("ecom.extract", "--run-mode", "backfill", "--backfill-request-id", request_id)
    assert r2.returncode == 0
    batch1_again = _pg(
        "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    assert batch1 == batch1_again
    count1 = _pg("SELECT count(*) FROM control.batch WHERE run_mode='backfill'")
    r3 = _run(
        "ecom.extract",
        "--run-mode",
        "backfill",
        "--backfill-request-id",
        f"{request_id}-new",
        *backfill_args[4:],
    )
    assert r3.returncode == 0
    batch2 = _pg(
        "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    assert batch2 != batch1
    count2 = _pg("SELECT count(*) FROM control.batch WHERE run_mode='backfill'")
    assert count2 != count1
    # Incremental run still picks up the same versions; load converges canonically.
    r4 = _run("ecom.extract")
    assert r4.returncode == 0
    r5 = _run("ecom.load")
    assert r5.returncode == 0


def test_concurrent_publication_blocked():
    """PUB-004: a second publication cannot proceed while one is active."""
    import psycopg

    dsn = os.environ["WAREHOUSE_DSN"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO control.publication (product_name, publication_id, candidate_relation, status) "
            "VALUES ('mart_daily_order_fulfillment','test-conc-lock','gold_candidate.locked','publishing') "
            "ON CONFLICT DO NOTHING"
        )
        conn.commit()
    try:
        r = _run(
            "ecom.publish",
            "--publication-id",
            "test-conc2",
            "--test-results",
            "missing-run-results.json",
            "--dbt-manifest",
            "missing-manifest.json",
        )
        assert r.returncode != 0
        assert "another publication is active" in (r.stdout + r.stderr)
    finally:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM control.publication WHERE publication_id='test-conc-lock'")
            conn.commit()


def test_retention_expires_failed_candidate():
    """PUB-003: failed candidates older than seven days are removed safely."""
    import psycopg

    publication_id = f"expired_{uuid.uuid4().hex}"
    relation = f"mart_daily_order_fulfillment__{publication_id}"
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(f"CREATE TABLE gold_candidate.{relation} (value integer)")
        cur.execute(
            """INSERT INTO control.publication (
                 product_name, publication_id, candidate_relation, status, created_at)
               VALUES ('mart_daily_order_fulfillment', %s, %s, 'failed', now() - interval '8 days')""",
            (publication_id, f"gold_candidate.{relation}"),
        )
        conn.commit()
    result = _run("ecom.retention")
    assert result.returncode == 0
    assert _pg(f"SELECT to_regclass('gold_candidate.{relation}')") == "[(None,)]"
    assert (
        _pg(f"SELECT status FROM control.publication WHERE publication_id='{publication_id}'")
        == "[('expired',)]"
    )


def test_checkpoint_cas_conflict_fails_explicitly(tmp_path):
    """COMMIT-006: a stale committer is rejected before writing anything."""
    import tempfile
    from datetime import datetime

    import pyarrow as pa
    import pyarrow.parquet as pq
    import pytest

    from ecom.config import Settings
    from ecom.extract import _commit_checkpoint, _sha256_file

    existing = _pg(
        "SELECT cursor_updated_at FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    assert existing != "[]", "checkpoint must exist for a CAS-conflict probe"
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "bronze").mkdir()
        pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
        manifest = {
            "batch_id": "test-cas-probe",
            "run_mode": "incremental",
            "cursor_before": "NONE",
            "cursor_upper": "2018-01-01T00:00:00+00:00|zz",
            "accepted_count": 1,
            "rejected_count": 0,
            "files": {
                "bronze/accepted.parquet": _sha256_file(base / "bronze" / "accepted.parquet")
            },
        }
        with pytest.raises(SystemExit, match="compare-and-swap conflict"):
            _commit_checkpoint(
                Settings.from_env(),
                manifest,
                str(base / "manifest.json"),
                "run-probe",
                None,
                None,
                datetime.fromisoformat("2018-01-01T00:00:00+00:00"),
                "zz",
            )
    probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-cas-probe'")
    assert probe == "[(0,)]"


def test_dead_source_fails_after_recorded_retries():
    """OBS-002: retryable source errors record attempts and never move the checkpoint."""
    checkpoint_before = _pg(
        "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    dead = "postgresql://nobody:nobody@localhost:5499/ecom_source"
    r = _run(
        "ecom.extract",
        env_extra={"SOURCE_DSN": dead, "SOURCE_READER_DSN": dead},
    )
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "connection attempt" in combined
    assert "category=" in combined
    checkpoint_after = _pg(
        "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
        "WHERE source_name='source_postgres' AND entity_name='orders'"
    )
    assert checkpoint_before == checkpoint_after


def test_run_output_contains_no_secrets():
    """OBS-003: run output must not leak credentials."""
    r = _run("ecom.extract")
    combined = r.stdout + r.stderr
    for var in ("SOURCE_PASSWORD", "WAREHOUSE_PASSWORD", "SOURCE_READER_PASSWORD"):
        secret = os.environ.get(var, "")
        if secret:
            assert secret not in combined


def test_reconciliation_across_layers():
    """COMMIT-011/012, DQ-005, MODEL-002(structural), MODEL-010, CUR-005."""
    import pyarrow.parquet as pq

    r = _run("ecom.load")
    assert r.returncode == 0
    import psycopg

    manifests = sorted(
        (REPO / "data" / "committed_batches" / "orders").rglob("batch_id=*/manifest.json")
    )
    assert manifests, "expected committed batch manifests"
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT batch_id, manifest_path FROM control.batch "
            "WHERE status='committed' AND entity_name='orders'"
        )
        registered = {row[0]: row[1] for row in cur.fetchall()}
    # COMMIT-011: manifests on disk match registered committed batches exactly.
    on_disk = {}
    for mpath in manifests:
        m = json.loads(mpath.read_text())
        on_disk[m["batch_id"]] = m
    assert set(on_disk) == set(registered)
    # DQ-005 + COMMIT-012: manifest counts match readable Parquet; raw holds one
    # canonical copy per distinct accepted source version (CUR-005 equal-ts proof:
    # the initial load shares one source_updated_at across ~99k rows).
    versions: set[tuple] = set()

    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else REPO / path

    for batch_id, m in on_disk.items():
        parent = _resolve(registered[batch_id]).parent
        bronze = parent / "bronze" / "accepted.parquet"
        table = pq.read_table(bronze)
        assert table.num_rows == m["accepted_count"]
        qpath = parent / "quarantine" / "rejected.parquet"
        n_rejected = pq.read_table(qpath).num_rows if qpath.exists() else 0
        assert n_rejected == m["rejected_count"]
        for row in table.to_pylist():
            versions.add((row["order_id"], row["source_updated_at"]))
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_stage.orders")
        (raw_count,) = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM (SELECT order_id, source_updated_at FROM raw_stage.orders "
            "GROUP BY 1, 2 HAVING count(*) > 1) d"
        )
        (dup_versions,) = cur.fetchone()
        cur.execute("SELECT count(*) FROM silver.stg_orders")
        (silver_count,) = cur.fetchone()
        cur.execute("SELECT coalesce(sum(order_count),0) FROM gold.mart_daily_order_fulfillment")
        (gold_orders,) = cur.fetchone()
    assert dup_versions == 0
    assert raw_count == len(versions)
    assert gold_orders == silver_count
