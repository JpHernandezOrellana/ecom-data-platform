"""Phase 2A order_items tests: composite cursor (ADR-006) and vertical slice (needs DB)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ecom.cursor import build_predicate

REPO = Path(__file__).resolve().parents[1]


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
