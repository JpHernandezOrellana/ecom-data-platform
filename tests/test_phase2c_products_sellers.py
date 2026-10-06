"""Phase 2C products/sellers tests: simple-key dimensions reusing ADR-002 (ADR-008)."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_FIXTURE_PRODUCT_IDS = (
    "aa5d5eb4af85d064f9f3b62f8826eb66",
    "9d980378e1315dc8396f77ed841edbec",
)
_FIXTURE_SELLER_IDS = (
    "1b0f9736d286819f6508e2668c487500",
    "9d980378e1315dc8396f77ed841edbec",
)


@pytest.fixture(scope="module", autouse=True)
def _flush_and_clean_products_sellers_module():
    """Module-level final sweep, mirroring test_phase2a_items.py's rationale."""
    yield
    import psycopg

    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "ecom.load_products"],
        cwd=REPO,
        env=env,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        [sys.executable, "-m", "ecom.load_sellers"],
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
                "DELETE FROM source.products WHERE product_id != ALL(%s)",
                (list(_FIXTURE_PRODUCT_IDS),),
            )
            cur.execute(
                "DELETE FROM source.sellers WHERE seller_id != ALL(%s)",
                (list(_FIXTURE_SELLER_IDS),),
            )
            conn.commit()
        with psycopg.connect(warehouse_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM raw_stage.products WHERE product_id != ALL(%s)",
                (list(_FIXTURE_PRODUCT_IDS),),
            )
            cur.execute(
                "DELETE FROM raw_stage.sellers WHERE seller_id != ALL(%s)",
                (list(_FIXTURE_SELLER_IDS),),
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


def _insert_source_product(product_id: str, source_updated_at: datetime) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.products (product_id, product_category_name, source_created_at, source_updated_at)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (product_id) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (product_id, "test_category", source_updated_at, source_updated_at),
        )
        conn.commit()


def _delete_source_product(product_id: str) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.products WHERE product_id = %s", (product_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.products WHERE product_id = %s", (product_id,))
        conn.commit()


def _insert_source_seller(seller_id: str, source_updated_at: datetime) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO source.sellers (seller_id, seller_zip_code_prefix, seller_city, seller_state,
               source_created_at, source_updated_at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (seller_id) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at""",
            (seller_id, "00000", "test city", "SP", source_updated_at, source_updated_at),
        )
        conn.commit()


def _delete_source_seller(seller_id: str) -> None:
    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM source.sellers WHERE seller_id = %s", (seller_id,))
        conn.commit()
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw_stage.sellers WHERE seller_id = %s", (seller_id,))
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
def test_products_vertical_slice_is_idempotent_and_reconciles():
    """Phase 2C: bootstrap -> extract -> load for products converges (ADR-008)."""
    import psycopg

    fixture = REPO / "tests" / "fixtures" / "products_small.csv"
    try:
        r1 = _run(
            "ecom.bootstrap_products",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-products-boot",
            "--allow-unverified-input",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "accepted=2 rejected=0" in r1.stdout

        r2 = _run(
            "ecom.bootstrap_products",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-products-boot-2",
            "--allow-unverified-input",
        )
        assert r2.returncode == 0, r2.stdout + r2.stderr

        r3 = _run("ecom.extract_products")
        assert r3.returncode == 0, r3.stdout + r3.stderr
        assert "extraction ok" in r3.stdout

        r4 = _run("ecom.extract_products")
        assert r4.returncode == 0
        assert "no_op" in (r4.stdout + r4.stderr)

        r5 = _run("ecom.load_products")
        assert r5.returncode == 0
        r6 = _run("ecom.load_products")
        assert r6.returncode == 0

        with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM raw_stage.products WHERE product_id = ANY(%s)",
                (list(_FIXTURE_PRODUCT_IDS),),
            )
            (count,) = cur.fetchone()
            assert count == 2, "double load must not duplicate rows"
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source.products WHERE product_id = ANY(%s)",
                (list(_FIXTURE_PRODUCT_IDS),),
            )
            conn.commit()


@pytest.mark.integration
def test_sellers_vertical_slice_is_idempotent_and_reconciles():
    """Phase 2C: bootstrap -> extract -> load for sellers converges (ADR-008)."""
    import psycopg

    fixture = REPO / "tests" / "fixtures" / "sellers_small.csv"
    try:
        r1 = _run(
            "ecom.bootstrap_sellers",
            "--csv",
            str(fixture),
            "--attempt-id",
            "test-sellers-boot",
            "--allow-unverified-input",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "accepted=2 rejected=0" in r1.stdout

        r2 = _run("ecom.extract_sellers")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "extraction ok" in r2.stdout

        r3 = _run("ecom.extract_sellers")
        assert r3.returncode == 0
        assert "no_op" in (r3.stdout + r3.stderr)

        r4 = _run("ecom.load_sellers")
        assert r4.returncode == 0
        r5 = _run("ecom.load_sellers")
        assert r5.returncode == 0

        with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM raw_stage.sellers WHERE seller_id = ANY(%s)",
                (list(_FIXTURE_SELLER_IDS),),
            )
            (count,) = cur.fetchone()
            assert count == 2, "double load must not duplicate rows"
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM source.sellers WHERE seller_id = ANY(%s)",
                (list(_FIXTURE_SELLER_IDS),),
            )
            conn.commit()


@pytest.mark.integration
def test_products_crash_recovery_reuses_committed_batch():
    """Mirrors ORD/items crash-after-publish recovery (ADR-002), for products."""
    product_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_product(product_id, ts)
        r1 = _run("ecom.extract_products", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted((REPO / "data" / "committed_batches" / "products").rglob("manifest.json"))
        r2 = _run("ecom.extract_products")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted((REPO / "data" / "committed_batches" / "products").rglob("manifest.json"))
        assert len(after) == len(before), "retry must not write a second committed batch"
        assert "recovered committed batch" in r2.stdout or "extraction ok" in r2.stdout
    finally:
        _delete_source_product(product_id)


@pytest.mark.integration
def test_sellers_crash_recovery_reuses_committed_batch():
    """Symmetry check for sellers (ADR-008)."""
    seller_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_seller(seller_id, ts)
        r1 = _run("ecom.extract_sellers", "--fail-after-publish")
        assert r1.returncode != 0
        assert "injected crash" in (r1.stdout + r1.stderr)
        before = sorted((REPO / "data" / "committed_batches" / "sellers").rglob("manifest.json"))
        r2 = _run("ecom.extract_sellers")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        after = sorted((REPO / "data" / "committed_batches" / "sellers").rglob("manifest.json"))
        assert len(after) == len(before), "retry must not write a second committed batch"
        assert "recovered committed batch" in r2.stdout or "extraction ok" in r2.stdout
    finally:
        _delete_source_seller(seller_id)


@pytest.mark.integration
def test_products_checkpoint_cas_conflict_fails_explicitly():
    """COMMIT-006 equivalent for products: a stale committer is rejected before writing."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from ecom.config import Settings
    from ecom.extract_products import _commit_checkpoint

    product_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_product(product_id, ts)
        r = _run("ecom.extract_products")
        assert r.returncode == 0, r.stdout + r.stderr

        existing = _pg(
            "SELECT cursor_updated_at FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='products'"
        )
        assert existing != "[]", "checkpoint must exist for a CAS-conflict probe"
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "bronze").mkdir()
            pq.write_table(pa.table({"a": [1]}), base / "bronze" / "accepted.parquet")
            from ecom.extract import _sha256_file

            manifest = {
                "batch_id": "test-products-cas-probe",
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
        probe = _pg("SELECT count(*) FROM control.batch WHERE batch_id='test-products-cas-probe'")
        assert probe == "[(0,)]"
    finally:
        _delete_source_product(product_id)


@pytest.mark.integration
def test_products_backfill_leaves_normal_checkpoint():
    """COMMIT-008/009/010 equivalent for products."""
    product_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    request_id = f"products-close-{uuid.uuid4().hex}"
    try:
        _insert_source_product(product_id, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='products'"
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
        r1 = _run("ecom.extract_products", *backfill_args)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "extraction ok" in r1.stdout
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='products'"
        )
        assert checkpoint_before == checkpoint_after
        assert (
            _pg(f"SELECT status FROM control.backfill_request WHERE request_id='{request_id}'")
            == "[('committed',)]"
        )
        r2 = _run("ecom.extract_products")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        r3 = _run("ecom.load_products")
        assert r3.returncode == 0, r3.stdout + r3.stderr
    finally:
        _delete_source_product(product_id)


@pytest.mark.integration
def test_products_breaking_operational_schema_fails_closed():
    """Incompatible source change fails before publication; checkpoint does not move."""
    import psycopg

    product_id = uuid.uuid4().hex
    ts = datetime.now(UTC)
    try:
        _insert_source_product(product_id, ts)
        checkpoint_before = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='products'"
        )
        manifests_before = sorted(
            (REPO / "data" / "committed_batches" / "products").rglob("manifest.json")
        )
        dsn = os.environ["SOURCE_DSN"]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE source.products RENAME COLUMN product_category_name TO category_broken"
            )
            conn.commit()
        try:
            r = _run("ecom.extract_products")
            assert r.returncode != 0
            assert "no_op" not in (r.stdout + r.stderr)
        finally:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE source.products RENAME COLUMN category_broken TO product_category_name"
                )
                conn.commit()
        checkpoint_after = _pg(
            "SELECT cursor_updated_at, cursor_key FROM control.checkpoint "
            "WHERE source_name='source_postgres' AND entity_name='products'"
        )
        manifests_after = sorted(
            (REPO / "data" / "committed_batches" / "products").rglob("manifest.json")
        )
        assert checkpoint_before == checkpoint_after
        assert manifests_before == manifests_after
    finally:
        _delete_source_product(product_id)
