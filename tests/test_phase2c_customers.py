"""Phase 2C slice 2 customers tests: simple-key dimension reusing ADR-002 (ADR-008).

Unlike products/sellers (loosely coupled to order_items, bootstrapped inside pytest),
customers is tightly coupled 1:1 with orders and is bootstrapped/extracted/loaded as an
explicit CI step right after orders itself (see .github/workflows/ci.yml), so that the
orphan check (an order's customer_id must exist in stg_customers) never sees a trivially
empty customers dimension against a non-empty orders fact at the baseline dbt build. These
tests therefore assume that bootstrap has already happened, mirroring
tests/test_integration.py's assumptions for `orders` itself.
"""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_FIXTURE_CUSTOMER_IDS = (
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "dddddddddddddddddddddddddddddddd",
    "ffffffffffffffffffffffffffffffff",
)


@pytest.fixture(scope="module", autouse=True)
def _flush_and_clean_customers_module():
    """Module-level final sweep, mirroring test_phase2c_products_sellers.py's rationale."""
    yield
    import psycopg

    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "ecom.load_customers"],
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
                "DELETE FROM source.customers WHERE customer_id != ALL(%s)",
                (list(_FIXTURE_CUSTOMER_IDS),),
            )
            conn.commit()
        with psycopg.connect(warehouse_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM raw_stage.customers WHERE customer_id != ALL(%s)",
                (list(_FIXTURE_CUSTOMER_IDS),),
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


def _insert_source_customer(customer_id: str, source_updated_at: datetime) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.customers (
                 customer_id, customer_unique_id, customer_zip_code_prefix, customer_city,
                 customer_state, source_created_at, source_updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (customer_id) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (
                customer_id,
                uuid.uuid4().hex,
                "00000",
                "test city",
                "SP",
                source_updated_at,
                source_updated_at,
            ),
        )
        conn.commit()


def _delete_source_customer(customer_id: str) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.customers WHERE customer_id = %s", (customer_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.customers WHERE customer_id = %s", (customer_id,))
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
def test_customers_idempotent_rerun_is_noop():
    """Mirrors orders' test_idempotent_rerun_is_noop: CI already bootstrapped/extracted."""
    r = _run("ecom.extract_customers")
    assert "no_op" in (r.stdout + r.stderr) or r.returncode == 0


@pytest.mark.integration
def test_customers_double_load_is_idempotent():
    import psycopg

    r = _run("ecom.load_customers")
    assert r.returncode == 0, r.stdout + r.stderr
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM raw_stage.customers WHERE customer_id = ANY(%s)",
            (list(_FIXTURE_CUSTOMER_IDS),),
        )
        (count,) = cur.fetchone()
        assert count == 3, "fixture customers must have loaded exactly once each"


@pytest.mark.integration
def test_customers_crash_recovery_reuses_committed_batch():
    """Mirrors ORD/items/products crash-after-publish recovery (ADR-002)."""
    customer_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_customer(customer_id, ts)
        r1 = _run("ecom.extract_customers", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted((REPO / "data" / "committed_batches" / "customers").rglob("manifest.json"))
        r2 = _run("ecom.extract_customers")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted((REPO / "data" / "committed_batches" / "customers").rglob("manifest.json"))
        assert len(after) == len(before), "retry must not write a second committed batch"
        assert "recovered committed batch" in r2.stdout or "extraction ok" in r2.stdout
    finally:
        _delete_source_customer(customer_id)


@pytest.mark.integration
def test_customers_checkpoint_cas_conflict_fails_explicitly():
    """COMMIT-006 equivalent for customers: a stale committer is rejected before writing."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from ecom.config import Settings
    from ecom.extract_customers import _commit_checkpoint

    customer_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_customer(customer_id, ts)
        r = _run("ecom.extract_customers")
        assert r.returncode == 0, r.stdout + r.stderr

        existing = _pg(
            "SELECT cursor_updated_at FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='customers'"
        )
        assert existing != "[]", "checkpoint must exist for a CAS-conflict probe"
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "bronze").mkdir()
            pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
            from ecom.extract import _sha256_file

            manifest = {
                "batch_id": "test-customers-cas-probe",
                "run_mode": "incremental",
                "cursor_before": "NONE",
                "cursor_upper": "2099-01-01T00:00:00+00:00|zz",
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
                    "zz",
                )
        probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-customers-cas-probe'")
        assert probe == "[(0,)]"
    finally:
        _delete_source_customer(customer_id)


@pytest.mark.integration
def test_customers_backfill_leaves_normal_checkpoint():
    """COMMIT-008/009/010 equivalent for customers."""
    customer_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    request_id = f"customers-close-{uuid.uuid4().hex}"
    try:
        _insert_source_customer(customer_id, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='customers'"
        )
        backfill_args = (
            "--run-mode",
            "backfill",
            "--backfill-request-id",
            request_id,
            "--backfill-from-ts",
            "2018-10-20T00:00:00+00:00",
            "--backfill-from-key",
            "0" * 32,
            "--backfill-to-ts",
            ts.isoformat(),
            "--backfill-to-key",
            "f" * 32,
            "--backfill-reason",
            "integration-test",
        )
        r1 = _run("ecom.extract_customers", *backfill_args)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "extraction ok" in r1.stdout
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='customers'"
        )
        assert checkpoint_before == checkpoint_after
        assert (
            _pg(f"SELECT status FROM control.backfill_request WHERE request_id='{request_id}'")
            == "[('committed',)]"
        )
        r2 = _run("ecom.extract_customers")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        r3 = _run("ecom.load_customers")
        assert r3.returncode == 0, r3.stdout + r3.stderr
    finally:
        _delete_source_customer(customer_id)


@pytest.mark.integration
def test_customers_breaking_operational_schema_fails_closed():
    """Incompatible source change fails before publication; checkpoint does not move."""
    import psycopg

    customer_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_customer(customer_id, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='customers'"
        )
        manifests_before = sorted(
            (REPO / "data" / "committed_batches" / "customers").rglob("manifest.json")
        )
        dsn = os.environ["SOURCE_DSN"]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE source.customers RENAME COLUMN customer_city TO city_broken")
            conn.commit()
        try:
            r = _run("ecom.extract_customers")
            assert r.returncode != 0
            assert "no_op" not in (r.stdout + r.stderr)
        finally:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE source.customers RENAME COLUMN city_broken TO customer_city"
                )
                conn.commit()
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='customers'"
        )
        manifests_after = sorted(
            (REPO / "data" / "committed_batches" / "customers").rglob("manifest.json")
        )
        assert checkpoint_before == checkpoint_after
        assert manifests_before == manifests_after
    finally:
        _delete_source_customer(customer_id)
