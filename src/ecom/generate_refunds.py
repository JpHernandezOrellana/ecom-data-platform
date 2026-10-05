"""Deterministic synthetic refund generator (parallel to ecom.mutate). ADR-005.

Olist contains no refund events. This tool appends clearly-labeled synthetic refund
events referencing an existing (order_id, payment_sequential), never claimed as observed
history. See contracts/source/operational_order_refunds.v1.yaml.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import UTC, datetime

from .config import Settings
from .db import connect, ensure_phase_2b_refunds_source_schema


def main() -> None:
    p = argparse.ArgumentParser(description="Deterministic synthetic refund generator")
    p.add_argument("--ts", default="2018-10-22T00:00:00+00:00")
    p.add_argument(
        "--reason", default="synthetic_demo_full_refund", help="Label stored in refund_reason"
    )
    p.add_argument(
        "--order-id",
        default="",
        help="Target a specific order_id instead of the deterministic default",
    )
    p.add_argument(
        "--payment-sequential",
        type=int,
        default=None,
        help="Target a specific payment_sequential (requires --order-id)",
    )
    args = p.parse_args()
    if bool(args.order_id) != bool(args.payment_sequential):
        raise SystemExit("--order-id and --payment-sequential must be supplied together")
    settings = Settings.from_env()
    ts = datetime.fromisoformat(args.ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    dsn = os.environ.get("SOURCE_DSN", settings.source_dsn)
    with connect(dsn) as conn:
        ensure_phase_2b_refunds_source_schema(conn)
        with conn.cursor() as cur:
            if args.order_id:
                cur.execute(
                    "SELECT p.order_id, p.payment_sequential, p.payment_value "
                    "FROM source.order_payments p "
                    "LEFT JOIN source.order_refunds r "
                    "  ON r.order_id = p.order_id AND r.payment_sequential = p.payment_sequential "
                    "WHERE p.order_id=%s AND p.payment_sequential=%s",
                    (args.order_id, args.payment_sequential),
                )
                row = cur.fetchone()
                if row is None:
                    raise SystemExit(
                        f"no such payment: order_id={args.order_id} "
                        f"payment_sequential={args.payment_sequential}"
                    )
                cur.execute(
                    "SELECT 1 FROM source.order_refunds WHERE order_id=%s AND payment_sequential=%s",
                    (args.order_id, args.payment_sequential),
                )
                if cur.fetchone():
                    print("no_op: payment already refunded")
                    return
            else:
                # Deterministic default: the lexicographically first payment not yet refunded.
                cur.execute(
                    """SELECT p.order_id, p.payment_sequential, p.payment_value
                       FROM source.order_payments p
                       LEFT JOIN source.order_refunds r
                         ON r.order_id = p.order_id AND r.payment_sequential = p.payment_sequential
                       WHERE r.refund_id IS NULL
                       ORDER BY p.order_id, p.payment_sequential
                       LIMIT 1"""
                )
                row = cur.fetchone()
                if row is None:
                    print("no_op: no unrefunded payment available")
                    return
            order_id, payment_sequential, payment_value = row
            refund_id = hashlib.sha256(
                f"{order_id}|{payment_sequential}|{ts.isoformat()}".encode()
            ).hexdigest()[:32]
            cur.execute(
                """INSERT INTO source.order_refunds (
                     refund_id, order_id, payment_sequential, refunded_amount, refund_reason,
                     refunded_at, source_created_at, source_updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (refund_id) DO NOTHING""",
                (
                    refund_id,
                    order_id,
                    payment_sequential,
                    payment_value,
                    args.reason,
                    ts,
                    ts,
                    ts,
                ),
            )
        conn.commit()
    print(
        f"refund generated: refund_id={refund_id} order_id={order_id} "
        f"payment_sequential={payment_sequential} amount={payment_value}"
    )


if __name__ == "__main__":
    main()
