from __future__ import annotations

import argparse
import re

from psycopg import sql

from .config import Settings
from .db import connect, ensure_phase_1_1_warehouse_schema

PRODUCTS = ("mart_daily_order_fulfillment", "mart_daily_commerce")
RELATION_RE = re.compile(
    r"^gold_candidate\.(mart_daily_order_fulfillment|mart_daily_commerce)__[A-Za-z0-9_-]+$"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Gold candidate retention")
    parser.parse_args()
    settings = Settings.from_env()
    with connect(settings.warehouse_dsn) as conn:
        ensure_phase_1_1_warehouse_schema(conn)
        with conn.cursor() as cur:
            for product in PRODUCTS:
                _retire_old_successful_candidates(cur, product)
                _expire_old_failed_candidates(cur, product)
        conn.commit()
    print("candidate retention complete")


def _retire_old_successful_candidates(cur, product: str) -> None:
    cur.execute(
        """SELECT publication_id, candidate_relation
           FROM control.publication
           WHERE product_name=%s AND status='published'
           ORDER BY created_at DESC OFFSET 5""",
        (product,),
    )
    for publication_id, relation in cur.fetchall():
        _drop_candidate(cur, product, relation)
        cur.execute(
            "UPDATE control.publication SET status='retired' WHERE product_name=%s AND publication_id=%s",
            (product, publication_id),
        )


def _expire_old_failed_candidates(cur, product: str) -> None:
    cur.execute(
        """SELECT publication_id, candidate_relation
           FROM control.publication
           WHERE product_name=%s AND status='failed' AND created_at < now() - interval '7 days'""",
        (product,),
    )
    for publication_id, relation in cur.fetchall():
        _drop_candidate(cur, product, relation)
        cur.execute(
            "UPDATE control.publication SET status='expired' WHERE product_name=%s AND publication_id=%s",
            (product, publication_id),
        )


def _drop_candidate(cur, product: str, relation: str) -> None:
    if not RELATION_RE.fullmatch(relation):
        raise SystemExit(f"refusing to drop unexpected candidate relation: {relation}")
    schema, table = relation.split(".", maxsplit=1)
    cur.execute("SELECT to_regclass(%s)", (f"gold.{product}",))
    view = cur.fetchone()[0]
    if view:
        cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (f"gold.{product}",))
        if table in cur.fetchone()[0]:
            raise SystemExit("refusing to delete the candidate referenced by certified Gold")
    cur.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    )


if __name__ == "__main__":
    main()
