"""Bootstrap contract/quarantine tests (need DB for accepted rows)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[1]


def _bootstrap(csv_text: str, attempt: str):
    import os

    tmp = REPO / f".tmp-{attempt}.csv"
    tmp.write_text(csv_text)
    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    try:
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "ecom.bootstrap",
                "--csv",
                str(tmp),
                "--attempt-id",
                attempt,
                "--allow-unverified-input",
            ],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return r
    finally:
        tmp.unlink(missing_ok=True)


GOOD_ROW = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,created,2018-01-02 10:00:00,,,,2018-01-10 00:00:00"
HEADER = "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date"


def test_structural_header_failure():
    r = _bootstrap("bad,header\n1,2\n", "test-bad-header")
    assert r.returncode != 0
    assert "unexpected header" in (r.stdout + r.stderr)


def _good(i: int) -> str:
    return (
        f"{i:032x},bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,created,"
        "2018-01-02 10:00:00,,,,2018-01-10 00:00:00"
    )


def test_threshold_exceeded_fails_after_durable_quarantine():
    """BOOT-004: rejected rows are durable even though the attempt fails."""
    bad = [
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,WRONG,"
        "2018-01-02 10:00:00,,,,2018-01-10 00:00:00"
        for _ in range(12)
    ]
    csv_text = f"{HEADER}\n" + "\n".join([_good(i) for i in range(2001, 2006)] + bad) + "\n"
    r = _bootstrap(csv_text, "test-threshold-over")
    assert r.returncode != 0
    assert "threshold exceeded" in (r.stdout + r.stderr)
    q = (
        REPO
        / "data"
        / "quarantine"
        / "bootstrap"
        / "orders"
        / "attempt_id=test-threshold-over"
        / "rejected.parquet"
    )
    assert q.exists()


def test_repeated_bootstrap_converges():
    """BOOT-005: an equivalent bootstrap leaves source state unchanged."""
    import os

    import psycopg

    ids = [f"{i:032x}" for i in range(3001, 3006)]
    csv_text = f"{HEADER}\n" + "\n".join(_good(i) for i in range(3001, 3006)) + "\n"
    try:
        r1 = _bootstrap(csv_text, "test-idem-one")
        assert r1.returncode == 0
        r2 = _bootstrap(csv_text, "test-idem-two")
        assert r2.returncode == 0
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT order_id, source_updated_at FROM source.orders WHERE order_id = ANY(%s) ORDER BY order_id",
                (ids,),
            )
            rows = cur.fetchall()
        assert [r[0] for r in rows] == ids
        assert len({r[1] for r in rows}) == 1, "repeated bootstrap must converge timestamps"
    finally:
        with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM source.orders WHERE order_id = ANY(%s)", (ids,))
            conn.commit()


def test_isolated_bad_row_quarantined_below_threshold():
    bad_status = "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,WRONG,2018-01-02 10:00:00,,,,2018-01-10 00:00:00"
    good_rows = "\n".join(
        f"{i:032x},bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,created,2018-01-02 10:00:00,,,,2018-01-10 00:00:00"
        for i in range(1, 102)
    )
    csv_text = f"{HEADER}\n{good_rows}\n{bad_status}\n"
    r = _bootstrap(csv_text, "test-quarantine-one")
    assert r.returncode == 0
    import os

    import psycopg

    with psycopg.connect(os.environ["SOURCE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM source.orders WHERE order_id LIKE '00000000000000000000000000000%'"
        )
        conn.commit()
    q = (
        REPO
        / "data"
        / "quarantine"
        / "bootstrap"
        / "orders"
        / "attempt_id=test-quarantine-one"
        / "rejected.parquet"
    )
    assert q.exists()
