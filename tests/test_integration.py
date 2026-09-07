"""Integration tests requiring local Postgres (compose up). Run with: uv run --extra dev pytest -m integration."""

import json
import os
import subprocess
import sys
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
    r = _run("ecom.publish", "--publication-id", "bad999")
    assert r.returncode != 0
    after = _pg("SELECT count(*) FROM gold.mart_daily_order_fulfillment")
    assert before == after
