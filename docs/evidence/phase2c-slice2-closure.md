# Phase 2C Slice 2 Closure Evidence

**Status:** Closed
**Closed on:** 2026-10-05
**Scope:** `customers` dimension ingestion only. No new Gold mart and no
new-vs-returning-customer metric — that remains explicitly deferred (SDD §37, ADR-008
"Deferred"). Scope confirmed with the project owner before implementation: ingest the
dimension and document the `customer_id`/`customer_unique_id` distinction; do not invent
customer-history semantics without their own ADR.

## Closed scope

- `contracts/source/olist_customers.v1.yaml`, `operational_customers.v1.yaml` accepted.
- `source.customers`, `raw_stage.customers`: simple single-column-key entity reusing
  ADR-002 unchanged, same pattern as `products`/`sellers` (ADR-008).
- `src/ecom/bootstrap_customers.py`, `extract_customers.py` (incremental + backfill),
  `load_customers.py`.
- dbt: `silver.stg_customers` (exposes both `customer_id` and `customer_unique_id`, no
  derived new-vs-returning flag), `assert_no_orphan_order_customers` (an order's
  `customer_id` must exist in `stg_customers` — never observed in the full Olist dataset,
  since `customer_id` is 1:1 with orders, but checked defensively per AGENTS.md §6.8).
- **Design difference from `products`/`sellers`:** `customers` is tightly coupled 1:1 with
  `orders` (unlike the loose `order_items` -> `products`/`sellers` relationship), so its
  bootstrap/extract/load run as an explicit CI step immediately after `orders`' own,
  before the baseline dbt build — not inside the integration pytest step. This avoids a
  real failure mode: if `customers` were left empty at baseline while `orders` already has
  fixture rows (orders bootstraps explicitly before baseline too), every order's
  `customer_id` would appear as an orphan at baseline and fail the build. This was caught
  by actually running the baseline build locally before finalizing the CI step placement,
  not assumed by analogy to products/sellers.
- Failure-injection tests (`tests/test_phase2c_customers.py`): idempotent rerun/double-load
  (mirroring `orders`' own pattern, since bootstrap already happened via CI), crash-after-
  publish recovery, checkpoint CAS conflict, bounded backfill, and breaking-operational-
  schema fail-closed.

## Verification

The local Docker source and warehouse services were healthy on a fresh volume. The
completed verification, following the exact CI command sequence plus the added customers
steps, produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 43 files already formatted
uv run --extra dev pytest -m "not integration" tests/     18 passed

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.bootstrap_customers --csv tests/fixtures/customers_small.csv ...
uv run python -m ecom.extract
uv run python -m ecom.load
uv run python -m ecom.extract_customers
uv run python -m ecom.load_customers
dbt seed                                          PASS=1 (71 rows)

PUBLICATION_ID=ci_baseline dbt build               PASS=62 WARN=0 ERROR=0 SKIP=0 TOTAL=62
publish all four products (baseline)

uv run --extra dev pytest -m integration -k "not test_reconciliation_across_layers" tests/
45 passed

uv run python -m ecom.load
PUBLICATION_ID=ci_final dbt build                  PASS=62 WARN=0 ERROR=0 SKIP=0 TOTAL=62
publish all four products (final)

uv run --extra dev pytest tests/test_integration.py::test_reconciliation_across_layers
1 passed

uv run python -m ecom.retention                    candidate retention complete
uv run --extra dev pytest -m "not integration" tests/     18 passed
```

### `customer_id`/`customer_unique_id` worked example

The fixture deliberately gives two distinct `customer_id` rows the same
`customer_unique_id`, to demonstrate the distinction without computing any metric from it:

```text
silver.stg_customers:
  customer_id=bbbb...  customer_unique_id=861eff4711a542e4b93843c6dd7febb0
  customer_id=dddd...  customer_unique_id=290c77bc529b7ac935b93aa66c333dc3
  customer_id=ffff...  customer_unique_id=861eff4711a542e4b93843c6dd7febb0   <- shares bbbb's unique id
```

This confirms the column is ingested and distinguishable, consistent with SDD §9.4,
without this slice asserting what a reader should do with it.

## Known limitations (carried forward, non-blocking)

- No new-vs-returning-customer metric or any Gold mart grouped by `customer_unique_id`
  exists. Defining one requires its own ADR (customer-history semantics, SDD §37).
- No `mutate_customers`-equivalent demo CLI; incremental-update demonstrations use direct
  test-only inserts, same as every other Phase 2 entity.
- Backfill mode for `customers` has not been exercised against equal-timestamp ties at
  scale.

## Phase 2C status

Both slices of the originally scoped Phase 2C entry work (`products`/`sellers`/category
commerce, and now `customers`) are closed. No further Phase 2C work is currently planned;
the recommended next phase is Phase 2D (BRL->CLP FX implementation, ADR-007) or a new,
separately ADR'd customer-history/seller-performance slice if a concrete requirement
justifies it.
