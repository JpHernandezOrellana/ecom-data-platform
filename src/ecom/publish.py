from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from psycopg import sql

from .config import Settings
from .db import connect, ensure_phase_1_1_warehouse_schema

PRODUCT = "mart_daily_order_fulfillment"
PUBLICATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
GOLD_COLUMNS = (
    "reporting_date",
    "order_count",
    "delivered_order_count",
    "canceled_order_count",
    "late_delivered_order_count",
    "late_delivery_eligible_order_count",
    "late_delivery_rate",
    "average_delivery_duration_days",
    "orders_with_fulfillment_quality_issue",
)


def main() -> None:
    p = argparse.ArgumentParser(description="Promote tested Gold candidate via stable view")
    p.add_argument("--publication-id", required=True)
    p.add_argument("--test-results", required=True, type=Path)
    p.add_argument("--dbt-manifest", required=True, type=Path)
    args = p.parse_args()
    if not PUBLICATION_ID_RE.fullmatch(args.publication_id):
        raise SystemExit(
            "publication id must contain only letters, digits, underscores, or hyphens"
        )
    settings = Settings.from_env()
    candidate = f"gold_candidate.{PRODUCT}__{args.publication_id}"
    with connect(settings.warehouse_dsn) as conn:
        ensure_phase_1_1_warehouse_schema(conn)
        with conn.cursor() as cur:
            # Lock detection happens before artifact inspection so a competing
            # invocation cannot do work while another publication is active.
            cur.execute(
                "SELECT publication_id FROM control.publication WHERE product_name=%s AND status='publishing' FOR UPDATE",
                (PRODUCT,),
            )
            if cur.fetchone():
                conn.rollback()
                raise SystemExit("another publication is active")
            try:
                _verify_dbt_candidate(args.publication_id, args.test_results, args.dbt_manifest)
                _verify_candidate_relation(cur, args.publication_id)
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
                SystemExit,
            ) as error:
                _record_failed_candidate(cur, args, candidate)
                conn.commit()
                raise SystemExit(
                    f"candidate verification failed; stable Gold view preserved: {error}"
                )
            cur.execute(
                """INSERT INTO control.publication (
                     product_name, publication_id, candidate_relation, status,
                     test_results_path, dbt_manifest_path, tested_at)
                   VALUES (%s,%s,%s,'publishing',%s,%s,now())
                   ON CONFLICT (product_name, publication_id) DO UPDATE SET
                     candidate_relation=EXCLUDED.candidate_relation,
                     status='publishing', test_results_path=EXCLUDED.test_results_path,
                     dbt_manifest_path=EXCLUDED.dbt_manifest_path, tested_at=EXCLUDED.tested_at""",
                (
                    PRODUCT,
                    args.publication_id,
                    candidate,
                    str(args.test_results),
                    str(args.dbt_manifest),
                ),
            )
            cur.execute(
                sql.SQL("CREATE OR REPLACE VIEW {}.{} AS SELECT {} FROM {}.{}").format(
                    sql.Identifier("gold"),
                    sql.Identifier(PRODUCT),
                    sql.SQL(", ").join(sql.Identifier(column) for column in GOLD_COLUMNS),
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


def _verify_dbt_candidate(publication_id: str, results_path: Path, manifest_path: Path) -> None:
    results = json.loads(results_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    expected_relation = f"gold_candidate.{PRODUCT}__{publication_id}"
    model_id = next(
        (
            node_id
            for node_id, node in manifest.get("nodes", {}).items()
            if node.get("resource_type") == "model"
            and node.get("name") == PRODUCT
            and node.get("relation_name", "").replace('"', "").endswith(expected_relation)
        ),
        None,
    )
    if model_id is None:
        raise ValueError("dbt manifest does not identify the requested candidate relation")

    statuses = {result["unique_id"]: result.get("status") for result in results.get("results", [])}
    if statuses.get(model_id) != "success":
        raise ValueError("dbt build did not successfully build the requested candidate")
    candidate_tests = [
        node_id
        for node_id, node in manifest.get("nodes", {}).items()
        if node.get("resource_type") == "test"
        and model_id in node.get("depends_on", {}).get("nodes", [])
    ]
    if not candidate_tests:
        raise ValueError("dbt manifest has no tests for the requested candidate")
    failed = [
        node_id for node_id in candidate_tests if statuses.get(node_id) not in {"pass", "success"}
    ]
    if failed:
        raise ValueError(f"dbt candidate tests did not pass: {', '.join(failed)}")


def _verify_candidate_relation(cur, publication_id: str) -> None:
    cur.execute(
        """SELECT EXISTS (
             SELECT 1 FROM pg_class relation
             JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname='gold_candidate' AND relation.relname=%s
           )""",
        (f"{PRODUCT}__{publication_id}",),
    )
    if not cur.fetchone()[0]:
        raise ValueError("requested candidate relation does not exist")


def _record_failed_candidate(cur, args: argparse.Namespace, candidate: str) -> None:
    cur.execute(
        """INSERT INTO control.publication (
             product_name, publication_id, candidate_relation, status, test_results_path, dbt_manifest_path)
           VALUES (%s,%s,%s,'failed',%s,%s)
           ON CONFLICT (product_name, publication_id) DO UPDATE SET
             status='failed', test_results_path=EXCLUDED.test_results_path,
             dbt_manifest_path=EXCLUDED.dbt_manifest_path""",
        (PRODUCT, args.publication_id, candidate, str(args.test_results), str(args.dbt_manifest)),
    )


if __name__ == "__main__":
    main()
