"""Phase 2B order_payments tests: vertical slice and failure injection (needs DB)."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_FIXTURE_ORDER_IDS = (
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "cccccccccccccccccccccccccccccccc",
    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
)


@pytest.fixture(scope="module", autouse=True)
def _flush_and_clean_order_payments_module():
    """Module-level final sweep; see the equivalent items fixture for the full rationale.

    `ecom.load_payments` loads every unloaded committed batch, not just the caller's, so
    per-test cleanup alone cannot guarantee no synthetic order_id survives into raw_stage.
    """
    yield
    import psycopg

    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "ecom.load_payments"],
        cwd=REPO,
        env=env,
        capture_output=True,
        check=False,
    )
    source_dsn = os.environ.get("SOURCE_DSN")
    warehouse_dsn = os.environ.get("WAREHOUSE_DSN")
    if not source_dsn or not warehouse_dsn:
        return
    try:
        with psycopg.connect(source_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source.order_payments WHERE order_id != ALL(%s)",
                (list(_FIXTURE_ORDER_IDS),),
            )
            conn.commit()
        with psycopg.connect(warehouse_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM raw_stage.order_payments WHERE order_id != ALL(%s)",
                (list(_FIXTURE_ORDER_IDS),),
            )
            conn.commit()
    except psycopg.OperationalError:
        pass


def _pg(query: str) -> str:
    import psycopg

    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(query)
        try:
            return str(cur.fetchall())
        except psycopg.ProgrammingError:
            return "ok"


def _insert_source_payment(order_id: str, seq: int, source_updated_at: datetime) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.order_payments (
                 order_id, payment_sequential, payment_type, payment_installments,
                 payment_value, source_created_at, source_updated_at)
               VALUES (%s,%s,'credit_card',1,%s,%s,%s)
               ON CONFLICT (order_id, payment_sequential) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (order_id, seq, "10.00", source_updated_at, source_updated_at),
        )
        conn.commit()


def _delete_source_payment(order_id: str) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.order_payments WHERE order_id = %s", (order_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.order_payments WHERE order_id = %s", (order_id,))
        conn.commit()


def _run(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.integration
def test_order_payments_vertical_slice_is_idempotent_and_reconciles():
    """Phase 2B: bootstrap -> extract -> load for order_payments converges."""
    import psycopg

    fixture = REPO / "tests" / "fixtures" / "order_payments_small.csv"
    try:
        r1 = _run(
            "ecom.bootstrap_payments",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-pay-boot",
            "--allow-unverified-input",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "accepted=3 rejected=0" in r1.stdout

        r2 = _run("ecom.extract_payments")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "extraction ok" in r2.stdout

        r3 = _run("ecom.extract_payments")
        assert r3.returncode == 0
        assert "no_op" in (r3.stdout + r3.stderr)

        r4 = _run("ecom.load_payments")
        assert r4.returncode == 0
        r5 = _run("ecom.load_payments")
        assert r5.returncode == 0

        with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw_stage.order_payments")
            (count,) = cur.fetchone()
            assert count == 3, "double load must not duplicate rows"
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source.order_payments WHERE order_id = ANY(%s)",
                (list(_FIXTURE_ORDER_IDS),),
            )
            conn.commit()


@pytest.mark.integration
def test_payments_crash_recovery_reuses_committed_batch():
    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        r1 = _run("ecom.extract_payments", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted(
            (REPO / "data" / "committed_batches" / "order_payments").rglob("manifest.json")
        )
        r2 = _run("ecom.extract_payments")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted(
            (REPO / "data" / "committed_batches" / "order_payments").rglob("manifest.json")
        )
        assert len(after) == len(before), "retry must not write a second committed batch"
    finally:
        _delete_source_payment(order_id)


@pytest.mark.integration
def test_payments_checkpoint_cas_conflict_fails_explicitly():
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from ecom.config import Settings
    from ecom.extract import _sha256_file
    from ecom.extract_payments import _commit_checkpoint

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        r = _run("ecom.extract_payments")
        assert r.returncode == 0, r.stdout + r.stderr

        existing = _pg(
            "SELECT cursor_updated_at FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_payments'"
        )
        assert existing != "[]"
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "bronze").mkdir()
            pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
            manifest = {
                "batch_id": "test-pay-cas-probe",
                "run_mode": "incremental",
                "cursor_before": "NONE",
                "cursor_upper": "2099-01-01T00:00:00+00:00|zz:9999",
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
                    datetime.fromisoformat("2099-01-01T00:00:00+00:00"),
                    "zz:9999",
                )
        probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-pay-cas-probe'")
        assert probe == "[(0,)]"
    finally:
        _delete_source_payment(order_id)


@pytest.mark.integration
def test_payments_backfill_leaves_normal_checkpoint():
    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    request_id = f"pay-close-{uuid.uuid4().hex}"
    try:
        _insert_source_payment(order_id, 1, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_payments'"
        )
        backfill_args = (
            "--run-mode",
            "backfill",
            "--backfill-request-id",
            request_id,
            "--backfill-from-ts",
            "2018-10-20T00:00:00+00:00",
            "--backfill-from-key",
            "00000000000000000000000000000000:0000",
            "--backfill-to-ts",
            ts.isoformat(),
            "--backfill-to-key",
            "ffffffffffffffffffffffffffffffff:9999",
            "--backfill-reason",
            "integration-test",
        )
        r1 = _run("ecom.extract_payments", *backfill_args)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_payments'"
        )
        assert checkpoint_before == checkpoint_after
        assert (
            _pg(f"SELECT status FROM control.backfill_request WHERE request_id='{request_id}'")
            == "[('committed',)]"
        )
        r2 = _run("ecom.extract_payments")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        r3 = _run("ecom.load_payments")
        assert r3.returncode == 0, r3.stdout + r3.stderr
    finally:
        _delete_source_payment(order_id)


@pytest.mark.integration
def test_payments_breaking_operational_schema_fails_closed():
    import psycopg

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_payments'"
        )
        manifests_before = sorted(
            (REPO / "data" / "committed_batches" / "order_payments").rglob("manifest.json")
        )
        dsn = os.environ["SOURCE_DSN"]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE source.order_payments RENAME COLUMN payment_value TO payment_value_broken"
            )
            conn.commit()
        try:
            r = _run("ecom.extract_payments")
            assert r.returncode != 0
            assert "no_op" not in (r.stdout + r.stderr)
        finally:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE source.order_payments RENAME COLUMN payment_value_broken TO payment_value"
                )
                conn.commit()
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_payments'"
        )
        manifests_after = sorted(
            (REPO / "data" / "committed_batches" / "order_payments").rglob("manifest.json")
        )
        assert checkpoint_before == checkpoint_after
        assert manifests_before == manifests_after
    finally:
        _delete_source_payment(order_id)
