# Phase 2B Closure Evidence

**Status:** Closed
**Closed on:** 2026-10-05
**Scope:** `order_payments` ingestion with reconciliation diagnostics, and the synthetic
refund event generator + `mart_daily_refunds`, per ADR-005. This document supersedes
[`docs/evidence/phase2b-payments-closure.md`](phase2b-payments-closure.md), which closed
only the first half; that document is retained as historical record of the intermediate
state, not as a current source of truth.

## Closed scope

### Payments ingestion (see `phase2b-payments-closure.md` for full detail)

- `contracts/source/olist_order_payments.v1.yaml`, `operational_order_payments.v1.yaml`.
- `source.order_payments` (ADR-006 composite cursor) and `raw_stage.order_payments`.
- `src/ecom/bootstrap_payments.py`, `extract_payments.py` (incremental + backfill),
  `load_payments.py`.
- `silver.int_payment_reconciliation`: diagnostic only, never a GMV/AOV input.
- `assert_no_orphan_order_payments`.

### Synthetic refunds (new in this closure)

- `contracts/source/operational_order_refunds.v1.yaml` (explicitly labeled synthetic) and
  `contracts/gold/mart_daily_refunds.v1.yaml`.
- `source.order_refunds` with a database `FOREIGN KEY (order_id, payment_sequential)` into
  `source.order_payments`; `refund_id` is a single opaque primary key (no ADR-006
  composite cursor needed for this entity).
- `src/ecom/generate_refunds.py`: deterministic synthetic generator, parallel to
  `ecom.mutate`. Default behavior refunds the lexicographically first unrefunded payment;
  `--order-id`/`--payment-sequential` target a specific payment. Refuses to double-refund
  an already-refunded payment.
- `src/ecom/extract_refunds.py` (incremental + backfill) and `load_refunds.py`, reusing
  `cursor.build_predicate`'s existing `key_column` parameter with a plain single-column
  key (`refund_id`) — no new cursor pattern required.
- dbt: `silver.stg_order_refunds`, `gold_candidate`/`gold` `mart_daily_refunds` (grained
  by refund date, `America/Santiago` — not purchase date), `assert_refunds_mart_metric_rules`,
  `assert_refunds_mart_reconciles_to_silver`, and `assert_refund_amount_within_payment`
  (defense-in-depth check that no refund exceeds its payment, re-verifying the
  generator's own invariant at the Silver layer).
- `src/ecom/publish.py` and `retention.py`: `mart_daily_refunds` added to the `PRODUCTS`
  registry; all three Gold products now publish and retain independently.
- `.github/workflows/ci.yml`: publish `mart_daily_refunds` at both baseline and final,
  alongside the other two products.
- Failure-injection tests for refunds (`tests/test_phase2b_refunds.py`): generator
  targeting/idempotency, refund-cannot-exceed-payment, FK rejection of a refund against a
  nonexistent payment, crash-after-publish recovery, checkpoint CAS conflict, and
  breaking-operational-schema fail-closed — matching the rigor applied to `order_items`
  and `order_payments`.
- Confirmed by direct query that `mart_daily_commerce.gmv_brl` is unaffected by a
  generated refund (never netted), per ADR-005.

## Verification

The local Docker source and warehouse services were healthy. The completed verification
on the documented local environment, following the exact CI command sequence, produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 32 files already formatted

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.extract
uv run python -m ecom.load

PUBLICATION_ID=ci_baseline dbt build   PASS=40 WARN=0 ERROR=0 SKIP=0 TOTAL=40
publish mart_daily_order_fulfillment, mart_daily_commerce, mart_daily_refunds (baseline)

uv run --extra dev pytest -m integration -k "not test_reconciliation_across_layers" tests/
32 passed, 19 deselected

uv run python -m ecom.load
PUBLICATION_ID=ci_final dbt build      PASS=40 WARN=0 ERROR=0 SKIP=0 TOTAL=40
publish mart_daily_order_fulfillment, mart_daily_commerce, mart_daily_refunds (final)

uv run --extra dev pytest tests/test_integration.py::test_reconciliation_across_layers
1 passed

uv run --extra dev pytest -m "not integration" tests/
18 passed
```

Total: 51 tests passing across the repository (18 unit + 32 integration + 1
reconciliation), 40/40 dbt tests at both baseline and final, all three Gold products
published successfully at both stages.

### Refund worked example (manual exploration, separate from the automated suite)

A manually generated refund against the fixture order `aaaa...` (full refund of its
BRL 110.00 payment) produced:

```text
gold_candidate.mart_daily_commerce:  2018-01-01  gmv_brl=100.00   <- unchanged by the refund
gold_candidate.mart_daily_refunds:   2018-10-21  refund_count=1  refunded_amount_brl=110.00
```

This confirms the ADR-005 invariant directly: GMV is never netted against refunds, and
the refund mart uses the refund's own date (`America/Santiago` conversion of
`2018-10-22T00:00:00+00:00` lands on `2018-10-21` local), not the order's purchase date.

## Known limitations (carried forward, non-blocking)

- No payment or refund timestamp exists in the Olist source itself; payments have none at
  all, and refund timestamps are entirely synthetic (generator-supplied), unlike
  `order_items`' `shipping_limit_date`.
- No `mutate_payments`/`mutate_refunds`-equivalent demo CLI beyond
  `ecom.generate_refunds` itself, which doubles as both the demo tool and the test
  fixture generator.
- Backfill mode (for `order_items`, `order_payments`, and `order_refunds`) has not been
  exercised against equal-timestamp ties at scale.
- `int_payment_reconciliation` has not been run against the full Olist dataset to
  confirm the ~1.3% disagreement rate documented in ADR-005's research.
- The synthetic refund generator always refunds 100% of a payment; it does not model
  partial refunds. This is an accepted simplification for a demo fixture, not a
  limitation of the underlying contract (`refunded_amount` has no such constraint).

## Phase 2C gates

Phase 2C (products, sellers, customers) is unstarted. Its entry work: category/seller
analytics models and the `customer_unique_id` vs `customer_id` distinction (SDD §9.4),
with no change to the Phase 2A/2B monetary grain.
