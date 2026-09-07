from __future__ import annotations

import argparse

from psycopg import sql

from .config import Settings
from .db import connect

PRODUCT = "mart_daily_order_fulfillment"


def main() -> None:
    p = argparse.ArgumentParser(description="Promote tested Gold candidate via stable view")
    p.add_argument("--publication-id", required=True)
    p.add_argument("--tests-passed", action="store_true")
    args = p.parse_args()
    settings = Settings.from_env()
    candidate = f"gold_candidate.{PRODUCT}__{args.publication_id}"
    with connect(settings.warehouse_dsn) as conn:
        with conn.cursor() as cur:
            if not args.tests_passed:
                cur.execute(
                    "INSERT INTO control.publication (product_name, publication_id, candidate_relation, status) VALUES (%s,%s,%s,'failed') ON CONFLICT DO NOTHING",
                    (PRODUCT, args.publication_id, candidate),
                )
                conn.commit()
                raise SystemExit("candidate tests failed; stable Gold view preserved")
            # single-publication guard
            cur.execute(
                "SELECT publication_id FROM control.publication WHERE product_name=%s AND status='publishing' FOR UPDATE",
                (PRODUCT,),
            )
            if cur.fetchone():
                conn.rollback()
                raise SystemExit("another publication is active")
            cur.execute(
                "INSERT INTO control.publication (product_name, publication_id, candidate_relation, status) VALUES (%s,%s,%s,'publishing') ON CONFLICT DO NOTHING",
                (PRODUCT, args.publication_id, candidate),
            )
            cur.execute(
                sql.SQL("CREATE OR REPLACE VIEW {}.{} AS SELECT * FROM {}.{}").format(
                    sql.Identifier("gold"),
                    sql.Identifier(PRODUCT),
                    sql.Identifier("gold_candidate"),
                    sql.Identifier(f"{PRODUCT}__{args.publication_id}"),
                )
            )
            cur.execute(
                "UPDATE control.publication SET status='published' WHERE product_name=%s AND publication_id=%s",
                (PRODUCT, args.publication_id),
            )
        conn.commit()
    print(f"published {PRODUCT} -> {candidate}")


if __name__ == "__main__":
    main()
