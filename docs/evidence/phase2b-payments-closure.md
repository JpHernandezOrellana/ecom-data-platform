# Phase 2B — Payments Ingestion Closure Evidence

**Status:** This slice closed. **Phase 2B as a whole remains open.**
**Closed on:** 2026-10-05
**Scope:** `order_payments` ingestion with the ADR-006 composite cursor and a payment-
reconciliation diagnostic model. This is the first of two deliverables in Phase 2B
(ADR-005). The second — a synthetic refund event generator and `mart_daily_refunds` — has
not started and is tracked separately; do not read this document as Phase 2B closure.

## Closed scope

- `contracts/source/olist_order_payments.v1.yaml` and
  `operational_order_payments.v1.yaml` accepted.
- `source.order_payments` (with `source_cursor_key` generated column, ADR-006) and
  `raw_stage.order_payments`.
- `src/ecom/bootstrap_payments.py`, `extract_payments.py` (incremental **and** backfill),
  `load_payments.py` — entity-specific modules mirroring the `order_items` pattern.
- dbt: `silver.stg_order_payments` and `silver.int_payment_reconciliation`, a **diagnostic
  only** model comparing `sum(payment_value)` to `price + freight_value` per order.
  Disagreement is expected (ADR-005: partial/installment payments, timing) and is never a
  blocking dbt test and never a GMV/AOV input.
- `assert_no_orphan_order_payments`: a payment whose `order_id` is absent from
  `stg_orders` fails the build. This is checked against `stg_orders` directly, not
  `int_order_commerce`, because an order can legitimately have payments without ever
  having items (775 such orders exist in the full Olist dataset, per the accepted
  contract's profiling) — that case must stay visible, not be conflated with a true
  orphan reference to a nonexistent order.
- Failure-injection test coverage for `order_payments` matching `order_items`: crash-
  after-publish recovery, checkpoint CAS conflict, bounded backfill request, and
  breaking-operational-schema fail-closed (`tests/test_phase2b_payments.py`).
- No changes to `mart_daily_commerce` or `mart_daily_order_fulfillment`: payments
  ingestion is additive and does not alter any certified Gold product.
- No CI workflow changes were needed: `order_payments` bootstrap/extract/load runs inside
  the integration pytest step, and its dbt models/tests run automatically as part of the
  existing dbt build steps, exactly like `order_items`.

## Verification

The local Docker source and warehouse services were healthy. The completed verification
on the documented local environment produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 28 files already formatted

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.extract
uv run python -m ecom.load

PUBLICATION_ID=phase2b_closure uv run --project . dbt build --project-dir dbt --profiles-dir dbt
PASS=30 WARN=0 ERROR=0 SKIP=0 TOTAL=30

uv run python -m ecom.publish --publication-id phase2b_closure ...
published mart_daily_order_fulfillment -> gold_candidate.mart_daily_order_fulfillment__phase2b_closure
uv run python -m ecom.publish --product mart_daily_commerce --publication-id phase2b_closure ...
published mart_daily_commerce -> gold_candidate.mart_daily_commerce__phase2b_closure

uv run --extra dev pytest tests/
45 passed
```

Post-suite convergence (after the full failure-injection and backfill test run, followed
by `ecom.load`, a final dbt build, publishing both products again, and
`ecom.retention`):

```text
raw_stage.order_payments           = 3   (one row per fixture payment; synthetic test
                                           payments are swept by the module-level cleanup
                                           fixture, see tests/test_phase2b_payments.py)
silver.stg_order_payments          = 3
silver.int_payment_reconciliation  = 3
```

Certified `silver.int_payment_reconciliation` (diagnostic, not a Gold product):

```text
order_id    reporting_date  item_plus_freight_brl  total_payment_value_brl  payment_count  payment_item_diff_brl  payments_reconcile_with_items
aaaa...      2018-01-01      110.00                 110.00                   1              0.00                    t
cccc...      2018-01-01      55.00                  55.00                    1              0.00                    t
eeee...      2017-02-18      55.00                  55.00                    1              0.00                    t
```

All three fixture orders reconcile exactly (`payment_item_diff_brl = 0`), as expected for
a small deterministic fixture; the full Olist dataset is documented (ADR-005, source
contract profiling) to disagree for roughly 1.3% of orders, which is why this model is
diagnostic rather than a blocking invariant.

## Known limitations (carried forward)

- No payment timestamp exists in the source; only simulator-owned
  `source_created_at`/`source_updated_at` support the cursor (unlike `order_items`, which
  has `shipping_limit_date`).
- No `mutate_payments`-equivalent CLI exists; incremental-update demonstrations use
  direct test-only inserts (`tests/test_phase2b_payments.py`).
- Backfill mode has not been exercised against equal-timestamp ties at scale.
- `int_payment_reconciliation` has not been run against the full Olist dataset to
  confirm the ~1.3% disagreement rate documented in ADR-005's research.

## Remaining Phase 2B work (not started)

Per ADR-005, Phase 2B is only complete once the synthetic refund event generator and
`mart_daily_refunds` exist:

1. A deterministic, clearly-labeled synthetic generator (parallel to `ecom.mutate`)
   appending refund events to a dedicated operational table, each referencing an
   existing `(order_id, payment_sequential)` and carrying `refund_id`,
   `refunded_amount`, `refund_reason`, and `refunded_at`.
2. `mart_daily_refunds`, grained by refund date (not purchase date), reporting
   `refunded_amount_brl` and `refund_count`.
3. `mart_daily_commerce.gmv_brl` is never reduced by refunds; a reader who wants a net
   figure computes `net_payment_value_brl` explicitly from both marts.
4. Contract, dbt tests, and failure-injection coverage for the refund generator,
   matching the rigor already applied to `order_items` and `order_payments`.

Only after this work lands should Phase 2B be marked closed and this document superseded
by a complete `docs/evidence/phase2b-closure.md`.
