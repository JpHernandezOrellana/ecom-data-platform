"""Phase 2A order_items tests: composite cursor (ADR-006) and vertical slice (needs DB)."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ecom.cursor import build_predicate

REPO = Path(__file__).resolve().parents[1]

_FIXTURE_ORDER_IDS = (
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "cccccccccccccccccccccccccccccccc",
    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
)


@pytest.fixture(scope="module", autouse=True)
def _flush_and_clean_order_items_module():
    """Module-level final sweep.

    `ecom.load_items` loads *every* unloaded committed batch, not just the one from the
    test that happens to call it. A test's own per-test cleanup can therefore run before a
    later test's `load_items` call surfaces its row in raw_stage, leaving an orphan behind
    for `assert_no_orphan_order_items`. Run load once at the end of the module and sweep
    any non-fixture order_id out of every layer, regardless of which test created it.
    """
    yield
    # This module also contains plain unit tests collected by the "not integration" run,
    # where no Postgres is reachable at all (SOURCE_DSN is set but nothing listens on
    # it); the connect() calls below fail fast and are caught, skipping the sweep.
    import psycopg

    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "ecom.load_items"],
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
                "DELETE FROM source.order_items WHERE order_id != ALL(%s)",
                (list(_FIXTURE_ORDER_IDS),),
            )
            conn.commit()
        with psycopg.connect(warehouse_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM raw_stage.order_items WHERE order_id != ALL(%s)",
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


def _insert_source_item(order_id: str, item_id: int, source_updated_at: datetime) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.order_items (
                 order_id, order_item_id, product_id, seller_id,
                 shipping_limit_at, shipping_limit_at_source_text, shipping_limit_at_timezone_resolution,
                 price, freight_value, source_created_at, source_updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,'synthetic_aware',%s,%s,%s,%s)
               ON CONFLICT (order_id, order_item_id) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (
                order_id,
                item_id,
                "a" * 32,
                "b" * 32,
                source_updated_at,
                source_updated_at.isoformat(),
                "10.00",
                "1.00",
                source_updated_at,
                source_updated_at,
            ),
        )
        conn.commit()


def _delete_source_item(order_id: str) -> None:
    """Remove the synthetic row from every layer it may have reached.

    These tests insert order_items for order_ids that deliberately do not exist in the
    orders fixture (they only probe the items pipeline), so any copy of them left behind
    in raw_stage would trip assert_no_orphan_order_items (GOLD-COM-ORPHAN-001) in the next
    dbt build. Unlike the orders suite (which relies on full volume resets between runs),
    this cleanup must be layer-complete because the two pipelines now share one dbt build.
    """
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.order_items WHERE order_id = %s", (order_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.order_items WHERE order_id = %s", (order_id,))
        conn.commit()


def _source_cursor_key(order_id: str, order_item_id: int) -> str:
    """Python mirror of the Postgres generated column (ADR-006)."""
    return f"{order_id}:{order_item_id:04d}"


def test_padded_cursor_key_sorts_numerically_not_lexicographically():
    """ADR-006: order_item_id 2 must sort before 10 despite being a shorter digit string."""
    oid = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    key_2 = _source_cursor_key(oid, 2)
    key_10 = _source_cursor_key(oid, 10)
    key_21 = _source_cursor_key(oid, 21)
    assert key_2 < key_10 < key_21


def test_build_predicate_accepts_composite_key_column():
    sql = build_predicate(True, "source_cursor_key")
    assert "(source_updated_at, source_cursor_key) >" in sql
    assert "ORDER BY source_updated_at, source_cursor_key" in sql
    # Default call site (orders) is unaffected.
    assert "order_id" in build_predicate(True)


pytestmark_integration = pytest.mark.integration


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
def test_order_items_vertical_slice_is_idempotent_and_reconciles():
    """Phase 2A: bootstrap -> extract -> load for order_items converges and reconciles."""
    import psycopg

    fixture = REPO / "tests" / "fixtures" / "order_items_small.csv"
    try:
        r1 = _run(
            "ecom.bootstrap_items",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-items-boot",
            "--allow-unverified-input",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "accepted=4 rejected=0" in r1.stdout

        r2 = _run(
            "ecom.bootstrap_items",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-items-boot-2",
            "--allow-unverified-input",
        )
        assert r2.returncode == 0, r2.stdout + r2.stderr

        r3 = _run("ecom.extract_items")
        assert r3.returncode == 0, r3.stdout + r3.stderr
        assert "extraction ok" in r3.stdout

        r4 = _run("ecom.extract_items")
        assert r4.returncode == 0
        assert "no_op" in (r4.stdout + r4.stderr)

        r5 = _run("ecom.load_items")
        assert r5.returncode == 0
        r6 = _run("ecom.load_items")
        assert r6.returncode == 0

        with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw_stage.order_items")
            (count,) = cur.fetchone()
            assert count == 4, "double load must not duplicate rows"

            cur.execute(
                "SELECT order_item_id FROM raw_stage.order_items "
                "WHERE order_id = 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee' ORDER BY order_item_id"
            )
            rows = [r[0] for r in cur.fetchall()]
            assert rows == [1, 2]
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source.order_items WHERE order_id IN "
                "('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','cccccccccccccccccccccccccccccccc',"
                "'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee')"
            )
            conn.commit()


@pytest.mark.integration
def test_items_crash_recovery_reuses_committed_batch():
    """Mirrors ORD crash-after-publish recovery (ADR-002), for the ADR-006 composite cursor."""
    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_item(order_id, 1, ts)
        r1 = _run("ecom.extract_items", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted(
            (REPO / "data" / "committed_batches" / "order_items").rglob("manifest.json")
        )
        r2 = _run("ecom.extract_items")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted((REPO / "data" / "committed_batches" / "order_items").rglob("manifest.json"))
        assert len(after) == len(before), "retry must not write a second committed batch"
        assert "recovered committed batch" in r2.stdout or "extraction ok" in r2.stdout
    finally:
        _delete_source_item(order_id)


@pytest.mark.integration
def test_items_checkpoint_cas_conflict_fails_explicitly():
    """COMMIT-006 equivalent for order_items: a stale committer is rejected before writing."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from ecom.config import Settings
    from ecom.extract_items import _commit_checkpoint

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_item(order_id, 1, ts)
        r = _run("ecom.extract_items")
        assert r.returncode == 0, r.stdout + r.stderr

        existing = _pg(
            "SELECT cursor_updated_at FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_items'"
        )
        assert existing != "[]", "checkpoint must exist for a CAS-conflict probe"
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "bronze").mkdir()
            pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
            from ecom.extract import _sha256_file

            manifest = {
                "batch_id": "test-items-cas-probe",
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
        probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-items-cas-probe'")
        assert probe == "[(0,)]"
    finally:
        _delete_source_item(order_id)


@pytest.mark.integration
def test_items_backfill_leaves_normal_checkpoint():
    """COMMIT-008/009/010 equivalent for order_items (ADR-006 composite backfill keys)."""
    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    request_id = f"items-close-{uuid.uuid4().hex}"
    try:
        _insert_source_item(order_id, 1, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_items'"
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
        r1 = _run("ecom.extract_items", *backfill_args)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "extraction ok" in r1.stdout
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_items'"
        )
        assert checkpoint_before == checkpoint_after
        batch1 = _pg(
            "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
            "AND entity_name='order_items' ORDER BY created_at DESC LIMIT 1"
        )
        assert (
            _pg(f"SELECT status FROM control.backfill_request WHERE request_id='{request_id}'")
            == "[('committed',)]"
        )
        r2 = _run(
            "ecom.extract_items", "--run-mode", "backfill", "--backfill-request-id", request_id
        )
        assert r2.returncode == 0, r2.stdout + r2.stderr
        batch1_again = _pg(
            "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
            "AND entity_name='order_items' ORDER BY created_at DESC LIMIT 1"
        )
        assert batch1 == batch1_again, "same request must reuse the same committed batch"

        r3 = _run(
            "ecom.extract_items",
            "--run-mode",
            "backfill",
            "--backfill-request-id",
            f"{request_id}-new",
            *backfill_args[4:],
        )
        assert r3.returncode == 0, r3.stdout + r3.stderr
        batch2 = _pg(
            "SELECT batch_id FROM control.batch WHERE run_mode='backfill' "
            "AND entity_name='order_items' ORDER BY created_at DESC LIMIT 1"
        )
        assert batch2 != batch1, "a new request id must be new evidence"

        r4 = _run("ecom.extract_items")
        assert r4.returncode == 0, r4.stdout + r4.stderr
        r5 = _run("ecom.load_items")
        assert r5.returncode == 0, r5.stdout + r5.stderr
    finally:
        _delete_source_item(order_id)


@pytest.mark.integration
def test_items_breaking_operational_schema_fails_closed():
    """Incompatible source change fails before publication; checkpoint does not move."""
    import psycopg

    order_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_item(order_id, 1, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_items'"
        )
        manifests_before = sorted(
            (REPO / "data" / "committed_batches" / "order_items").rglob("manifest.json")
        )
        dsn = os.environ["SOURCE_DSN"]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE source.order_items RENAME COLUMN price TO price_broken")
            conn.commit()
        try:
            r = _run("ecom.extract_items")
            assert r.returncode != 0
            assert "no_op" not in (r.stdout + r.stderr)
        finally:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("ALTER TABLE source.order_items RENAME COLUMN price_broken TO price")
                conn.commit()
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='order_items'"
        )
        manifests_after = sorted(
            (REPO / "data" / "committed_batches" / "order_items").rglob("manifest.json")
        )
        assert checkpoint_before == checkpoint_after
        assert manifests_before == manifests_after
    finally:
        _delete_source_item(order_id)
