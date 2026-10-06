# Phase 2C Slice 1 Closure Evidence

**Status:** Closed
**Closed on:** 2026-10-05
**Scope:** `products` and `sellers` dimension ingestion (ADR-008) and the new
`gold.mart_daily_category_commerce` mart, breaking BRL commerce value down by product
category at item grain. `customers` and seller-grained Gold metrics are explicitly out of
scope for this slice (see ADR-008 "Deferred").

## Closed scope

- `contracts/source/olist_products.v1.yaml`, `operational_products.v1.yaml`,
  `olist_sellers.v1.yaml`, `operational_sellers.v1.yaml`, and
  `contracts/gold/mart_daily_category_commerce.v1.yaml` accepted.
- `source.products`, `source.sellers`, `raw_stage.products`, `raw_stage.sellers`: simple
  single-column-key entities reusing ADR-002 unchanged (no ADR-006 composite cursor
  needed).
- `src/ecom/bootstrap_products.py`, `extract_products.py` (incremental + backfill),
  `load_products.py`, and the mirrored `*_sellers.py` modules.
- `dbt/seeds/product_category_name_translation.csv`: static reference data loaded as a
  dbt seed, not through the bootstrap/extract/load/checkpoint machinery (ADR-008 — no
  natural key mutation to track).
- dbt: `silver.stg_products` (null category bucketed as `"unknown"`), `silver.stg_sellers`,
  `silver.int_order_items_category` (item-grain, left join to `stg_products` so an orphan
  `product_id` fails the build instead of being silently merged into `"unknown"`),
  `gold_candidate`/`gold` `mart_daily_category_commerce`, with
  `assert_category_commerce_mart_metric_rules`,
  `assert_category_commerce_reconciles_to_commerce`,
  `assert_no_orphan_order_item_products` (GOLD-CAT-ORPHAN-001), and
  `assert_no_orphan_order_item_sellers` (symmetric check, no seller-grained metric yet).
- `src/ecom/publish.py` and `retention.py`: `mart_daily_category_commerce` added to both
  `PRODUCTS` registries (these are two independent hardcoded tuples in the two modules;
  `retention.py`'s was missed on a previous read and fixed in this slice).
- `.github/workflows/ci.yml`: added a `dbt seed` step and `mart_daily_category_commerce`
  to both baseline and final publish steps. Products/sellers bootstrap/extract/load happen
  inside the integration pytest step (`tests/test_phase2c_products_sellers.py`), not as
  separate CI steps — same pattern as `order_items`/`order_payments`, so the baseline
  candidate is trivially empty and the final candidate has real data.
- Failure-injection tests (`tests/test_phase2c_products_sellers.py`): vertical-slice
  idempotency for both entities, crash-after-publish recovery for both entities,
  checkpoint CAS conflict, bounded backfill, and breaking-operational-schema fail-closed —
  matching the rigor applied to `order_items`/`order_payments`.

## Verification

The local Docker source and warehouse services were healthy on a fresh volume. The
completed verification, following the exact CI command sequence plus the two added steps
(`dbt seed`, category-mart publish calls), produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 39 files already formatted
uv run --extra dev pytest -m "not integration" tests/     18 passed

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.extract
uv run python -m ecom.load
dbt seed                                          PASS=1 (71 rows)

PUBLICATION_ID=ci_baseline dbt build               PASS=57 WARN=0 ERROR=0 SKIP=0 TOTAL=57
publish all four products (baseline)

uv run --extra dev pytest -m integration -k "not test_reconciliation_across_layers" tests/
39 passed

uv run python -m ecom.load
PUBLICATION_ID=ci_final dbt build                  PASS=57 WARN=0 ERROR=0 SKIP=0 TOTAL=57
publish all four products (final)

uv run --extra dev pytest tests/test_integration.py::test_reconciliation_across_layers
1 passed

uv run python -m ecom.retention                    candidate retention complete
uv run --extra dev pytest -m "not integration" tests/     18 passed
```

### Category mart worked example (from the fixture data, final build)

```text
gold.mart_daily_category_commerce:
  2017-02-18  unknown        unknown           eligible_item_count=2  category_gmv_brl=50.00   category_freight_value_brl=5.00
  2018-01-01  beleza_saude   health_beauty     eligible_item_count=1  category_gmv_brl=100.00  category_freight_value_brl=10.00

gold.mart_daily_commerce:
  2017-02-18  gmv_brl=50.00
  2018-01-01  gmv_brl=100.00
```

This confirms GOLD-CAT-RECON-001 directly: `sum(category_gmv_brl)` by `reporting_date`
equals `mart_daily_commerce.gmv_brl` for the same date. The `2018-01-01` cohort's
`category_gmv_brl` correctly excludes the canceled order's item (price 50, category
`beleza_saude`) from the eligible total — only the delivered order's item (price 100)
counts, matching ADR-005's eligibility rule reapplied at item grain.

## Known limitations (carried forward, non-blocking)

- `customers` ingestion and the `customer_id`/`customer_unique_id` distinction are not
  part of this slice (ADR-008 "Deferred"); they require their own accepted
  customer-history ADR before implementation (`SDD.md` §37).
- `sellers` is ingested and orphan-checked (`assert_no_orphan_order_item_sellers`,
  symmetric to the product check) but has no seller-grained Gold metric yet; it exists as
  a dimension ready for a future seller-grained mart, not yet consumed by one.
- Backfill mode for `products`/`sellers` has not been exercised against equal-timestamp
  ties at scale (mirroring the same carried-forward limitation for `order_items`).
- No `mutate_products`/`mutate_sellers`-equivalent demo CLI; incremental-update
  demonstrations use direct test-only inserts, same as `order_items`/`order_payments`.

## Phase 2C slice 2 / further gates

Unstarted: `customers` ingestion and the `customer_id` vs `customer_unique_id` distinction
(SDD §9.4), and any seller-grained Gold mart. Both require their own ADR before
implementation per `AGENTS.md` §23.
