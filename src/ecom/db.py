from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg

_PHASE_1_1_MIGRATION = Path(__file__).resolve().parents[2] / "sql/warehouse/003_phase1_1.sql"
_PHASE_2A_WAREHOUSE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "sql/warehouse/004_order_items.sql"
)
_PHASE_2A_SOURCE_MIGRATION = Path(__file__).resolve().parents[2] / "sql/source/002_order_items.sql"


def connect(dsn: str, *, retries: int = 0, base_delay_s: float = 1.0) -> psycopg.Connection:
    """Open a connection with bounded retries.

    Every failed attempt is reported to stderr with its attempt count and failure
    category (OBS-002). Failures are never swallowed: after the final attempt the
    last error is re-raised and no checkpoint may advance.
    """
    if "connect_timeout" not in dsn:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}connect_timeout=5"
    last: psycopg.OperationalError | None = None
    for attempt in range(retries + 1):
        try:
            return psycopg.connect(dsn, autocommit=False)
        except psycopg.OperationalError as e:
            last = e
            print(
                f"connection attempt {attempt + 1}/{retries + 1} failed: "
                f"category={type(e).__name__} error={e}",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(base_delay_s * (2**attempt))
    assert last is not None
    raise last


def ensure_phase_1_1_warehouse_schema(conn: psycopg.Connection) -> None:
    """Apply the idempotent local migration for existing Compose volumes."""
    with conn.cursor() as cur:
        cur.execute(_PHASE_1_1_MIGRATION.read_text())
    conn.commit()


def ensure_phase_2a_warehouse_schema(conn: psycopg.Connection) -> None:
    """Apply the idempotent raw_stage.order_items migration (Phase 2A)."""
    with conn.cursor() as cur:
        cur.execute(_PHASE_2A_WAREHOUSE_MIGRATION.read_text())
    conn.commit()


def ensure_phase_2a_source_schema(conn: psycopg.Connection) -> None:
    """Apply the idempotent source.order_items migration (Phase 2A)."""
    with conn.cursor() as cur:
        cur.execute(_PHASE_2A_SOURCE_MIGRATION.read_text())
    conn.commit()
