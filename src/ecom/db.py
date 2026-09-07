from __future__ import annotations

import psycopg


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=False)
