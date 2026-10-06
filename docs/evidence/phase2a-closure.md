# Phase 2A Closure Evidence

**Status:** Closed
**Closed on:** 2026-10-05
**Scope:** `order_items` ingestion with a composite cursor key (ADR-006) and a BRL-only
`gold.mart_daily_commerce` (GMV, freight, AOV; ADR-005). Design accepted in ADR-005,
ADR-006, and ADR-007 (ADR-007's CLP implementation is explicitly deferred to Phase 2D and
is out of scope here).

> Historical closure snapshot: results and future-phase statements reflect the Phase 2A
> close. See [`docs/CURRENT_STATE.md`](../CURRENT_STATE.md) for current progress.

## Closed scope

- `contracts/source/olist_order_items.v1.yaml`, `operational_order_items.v1.yaml`, and
  `contracts/gold/mart_daily_commerce.v1.yaml` accepted.
- `source.order_items` (with the `source_cursor_key` generated column implementing
  ADR-006's padded composite key) and `raw_stage.order_items`.
- `src/ecom/bootstrap_items.py`, `extract_items.py` (incremental **and** backfill modes),
  `load_items.py` — entity-specific modules mirroring the orders pipeline.
- `src/ecom/publish.py` and `retention.py` parameterized by `--product` / a `PRODUCTS`
  registry; both `mart_daily_order_fulfillment` and `mart_daily_commerce` publish and
  retain independently.
- dbt: `silver.stg_order_items`, `silver.int_order_commerce`, `gold_candidate`/`gold`
  `mart_daily_commerce`, with `assert_commerce_mart_metric_rules`,
  `assert_commerce_mart_reconciles_to_silver`, and `assert_no_orphan_order_items`
  (GOLD-COM-ORPHAN-001 — an order_item whose order_id is absent from `stg_orders` fails
  the build rather than being silently excluded, per `AGENTS.md` §6.8).
- Failure-injection test coverage for `order_items` matching the orders suite: crash-
  after-publish recovery, checkpoint CAS conflict, bounded backfill request (stable
  re-run, new request = new evidence), and breaking-operational-schema fail-closed.
- Fixed a real cross-entity bug found while adding the second entity: `load.py`'s
  `control.batch` query had no `entity_name` filter and would have loaded `order_items`
  Bronze rows into `raw_stage.orders`; and `test_reconciliation_across_layers`'s manifest
  glob was not scoped to the `orders` subdirectory, so it silently mixed both entities'
  Bronze rows into one version set once `order_items` also committed batches.

## Verification

The local Docker source and warehouse services were healthy. The completed verification
on the documented local environment produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 24 files already formatted

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.extract
uv run python -m ecom.load

PUBLICATION_ID=phase2a_final uv run --project . dbt build --project-dir dbt --profiles-dir dbt
PASS=23 WARN=0 ERROR=0 SKIP=0 TOTAL=23

uv run python -m ecom.publish --publication-id phase2a_final ...
published mart_daily_order_fulfillment -> gold_candidate.mart_daily_order_fulfillment__phase2a_final
uv run python -m ecom.publish --product mart_daily_commerce --publication-id phase2a_final ...
published mart_daily_commerce -> gold_candidate.mart_daily_commerce__phase2a_final

uv run --extra dev pytest tests/
40 passed
```

Post-suite convergence (after the full failure-injection and backfill test run, followed
by `ecom.load`, a final dbt build, publishing both products again, and
`ecom.retention`):

```text
raw_stage.orders            = 5     (retains historical versions across test mutations)
silver.stg_orders           = 3     (one current row per order, fixture-bounded)
gold sum(order_count)       = 3
raw_stage.order_items       = 4     (one row per fixture item; synthetic test items are
                                      swept by the module-level cleanup fixture, see
                                      tests/test_phase2a_items.py)
silver.stg_order_items      = 4
silver.int_order_commerce   = 3     (one row per order with at least one item)
```

Certified `gold.mart_daily_commerce`:

```text
reporting_date | eligible_order_count | gmv_brl | freight_value_brl | gross_order_value_brl | aov_brl | canceled_item_value_brl | unavailable_item_value_brl
2017-02-18      1                      50.00     5.00                55.00                  50.00     0.00                      0.00
2018-01-01      1                      100.00    10.00               110.00                 100.00    50.00                     0.00
```

Spot-check against ADR-005: the `2018-01-01` cohort has two orders, one `delivered`
(price 100, freight 10) and one `canceled` (price 50, freight 5). `gmv_brl` correctly
equals 100 (the canceled order's 50 is excluded and reported separately as
`canceled_item_value_brl`), and `freight_value_brl` correctly equals 10 (only the
eligible order's freight, not the canceled order's). GMV excludes freight in both
cohorts, matching the ADR-005 definition exactly.

## Known Phase 2A limitations (carried forward, not blocking closure)

- Backfill mode exists for `order_items` but has not been exercised against a dataset
  with equal-timestamp ties at scale (the orders bootstrap deliberately creates many
  ties; the items fixture does not).
- No `mutate_items`-equivalent CLI exists; incremental-update demonstrations for items use
  direct test-only inserts (`tests/test_phase2a_items.py`) rather than a reusable command.
- CLP conversion (ADR-007) remains unimplemented by design — Phase 2D.
- Synthetic refunds and `mart_daily_refunds` (ADR-005) remain unimplemented — Phase 2B,
  after `order_payments`.

## Phase 2B gates

Phase 2B is unstarted. Its entry work: `order_payments` contract and ingestion, payment
reconciliation diagnostics against `price + freight_value`, and the synthetic refund
event generator feeding a `mart_daily_refunds` mart grained by refund date (ADR-005).
