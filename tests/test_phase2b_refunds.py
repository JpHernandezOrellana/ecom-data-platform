"""Phase 2B synthetic refunds tests: generator, vertical slice, failure injection (needs DB)."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def _flush_and_clean_order_refunds_module():
    """Module-level final sweep; see the equivalent items/payments fixtures for rationale."""
    yield
    import psycopg

    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "ecom.load_refunds"],
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
        # No bootstrap fixture exists for refunds (purely synthetic); every row created
        # across this module's tests is test-only, so the sweep clears the whole table.
        with psycopg.connect(source_dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM source.order_refunds")
            conn.commit()
        with psycopg.connect(warehouse_dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM raw_stage.order_refunds")
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


def _insert_source_payment(order_id: str, seq: int, ts: datetime, value: str = "10.00") -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.order_payments (
                 order_id, payment_sequential, payment_type, payment_installments,
                 payment_value, source_created_at, source_updated_at)
               VALUES (%s,%s,'credit_card',1,%s,%s,%s)
               ON CONFLICT (order_id, payment_sequential) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (order_id, seq, value, ts, ts),
        )
        conn.commit()


def _delete_order(order_id: str) -> None:
    """Delete a synthetic order's payment and any refund it has, from every layer."""
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.order_refunds WHERE order_id = %s", (order_id,))
        cur.execute("DELETE FROM source.order_payments WHERE order_id = %s", (order_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.order_refunds WHERE order_id = %s", (order_id,))
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
def test_refund_generator_targets_explicit_payment_and_reconciles():
    """Phase 2B: generate -> extract -> load for a targeted refund converges."""
    import psycopg

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts, value="42.50")
        r1 = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "refund generated" in r1.stdout
        assert f"order_id={order_id}" in r1.stdout

        r2 = _run("ecom.extract_refunds")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "extraction ok" in r2.stdout

        r3 = _run("ecom.load_refunds")
        assert r3.returncode == 0, r3.stdout + r3.stderr

        with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT refunded_amount FROM raw_stage.order_refunds WHERE order_id=%s",
                (order_id,),
            )
            (amount,) = cur.fetchone()
            assert str(amount) == "42.50"

        # A second explicit call for the same (order_id, payment_sequential) is a no_op:
        # the generator refuses to refund an already-refunded payment.
        r4 = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert r4.returncode == 0
        assert "no_op" in r4.stdout
    finally:
        _delete_order(order_id)


@pytest.mark.integration
def test_refund_amount_cannot_exceed_payment_value():
    """The generator always refunds the payment's own value; never more (ADR-005)."""
    import psycopg

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts, value="5.00")
        r = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT refunded_amount FROM source.order_refunds WHERE order_id=%s", (order_id,)
            )
            (amount,) = cur.fetchone()
            assert str(amount) == "5.00"
    finally:
        _delete_order(order_id)


@pytest.mark.integration
def test_refund_requires_existing_payment_fk():
    """A refund referencing a nonexistent payment is rejected by the database FK."""
    import psycopg

    order_id = uuid.uuid4().hex
    try:
        r = _run(
            "ecom.generate_refunds",
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert r.returncode != 0
        assert "no such payment" in (r.stdout + r.stderr)
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM source.order_refunds WHERE order_id = %s", (order_id,))
            conn.commit()


@pytest.mark.integration
def test_refunds_crash_recovery_reuses_committed_batch():
    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        g = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert g.returncode == 0, g.stdout + g.stderr
        r1 = _run("ecom.extract_refunds", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted(
            (REPO / "data" / "committed_batches" / "order_refunds").rglob("manifest.json")
        )
        r2 = _run("ecom.extract_refunds")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted(
            (REPO / "data" / "committed_batches" / "order_refunds").rglob("manifest.json")
        )
        assert len(after) == len(before), "retry must not write a second committed batch"
    finally:
        _delete_order(order_id)


@pytest.mark.integration
def test_refunds_checkpoint_cas_conflict_fails_explicitly():
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from ecom.config import Settings
    from ecom.extract import _sha256_file
    from ecom.extract_refunds import _commit_checkpoint

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        g = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert g.returncode == 0, g.stdout + g.stderr
        r = _run("ecom.extract_refunds")
        assert r.returncode == 0, r.stdout + r.stderr

        existing = _pg(
            "SELECT cursor_updated_at FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_refunds'"
        )
        assert existing != "[]"
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "bronze").mkdir()
            pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
            manifest = {
                "batch_id": "test-ref-cas-probe",
                "run_mode": "incremental",
                "cursor_before": "NONE",
                "cursor_upper": "2099-01-01T00:00:00+00:00|zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
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
                    "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
                )
        probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-ref-cas-probe'")
        assert probe == "[(0,)]"
    finally:
        _delete_order(order_id)


@pytest.mark.integration
def test_refunds_breaking_operational_schema_fails_closed():
    import psycopg

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_payment(order_id, 1, ts)
        g = _run(
            "ecom.generate_refunds",
            "--ts",
            ts.isoformat(),
            "--order-id",
            order_id,
            "--payment-sequential",
            "1",
        )
        assert g.returncode == 0, g.stdout + g.stderr
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_refunds'"
        )
        manifests_before = sorted(
            (REPO / "data" / "committed_batches" / "order_refunds").rglob("manifest.json")
        )
        dsn = os.environ["SOURCE_DSN"]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE source.order_refunds RENAME COLUMN refunded_amount TO refunded_amount_broken"
            )
            conn.commit()
        try:
            r = _run("ecom.extract_refunds")
            assert r.returncode != 0
            assert "no_op" not in (r.stdout + r.stderr)
        finally:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE source.order_refunds RENAME COLUMN refunded_amount_broken TO refunded_amount"
                )
                conn.commit()
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_refunds'"
        )
        manifests_after = sorted(
            (REPO / "data" / "committed_batches" / "order_refunds").rglob("manifest.json")
        )
        assert checkpoint_before == checkpoint_after
        assert manifests_before == manifests_after
    finally:
        _delete_order(order_id)
