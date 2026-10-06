# Current Project State

**Last updated:** 2026-10-05
**Current phase:** Phase 2C slice 1 closed (products + sellers dimensions +
`mart_daily_category_commerce`); evidence: `docs/evidence/phase2c-closure.md`
**Next phase:** Phase 2C slice 2 (customers, `customer_id` vs `customer_unique_id`) or
Phase 2D (FX/CLP)

This document is the required entry point for any agent or contributor before touching
code. It does not replace the formal sources — it routes to them. Read this file and
`AGENTS.md` first; read everything else only as the task requires (see §6).

## 1. What this project is

A local-first, zero-paid-infrastructure portfolio Data Engineering platform demonstrating
reliable incremental ingestion, immutable raw evidence, explicit data contracts, quality
isolation (quarantine), dbt modeling, idempotency, and failure recovery. Source dataset:
Olist Brazilian e-commerce orders. See [`README.md`](../README.md) for the full pitch.

## 2. What exists today (implemented and verified)

### Orders fulfillment (Phase 1.1, closed)

```text
Olist orders CSV -> source PostgreSQL -> bounded incremental extraction (cursor)
  -> committed batch envelope -> Bronze Parquet + Quarantine Parquet
  -> warehouse PostgreSQL (raw_stage) -> dbt Silver (stg_orders)
  -> versioned Gold candidate -> required tests -> certified Gold view
  (gold.mart_daily_order_fulfillment)
```

- Deterministic bootstrap from a checksum-pinned CSV, with contract validation and
  duplicate-key rejection (`src/ecom/bootstrap.py`).
- Bounded `(source_updated_at, order_id)` incremental extraction via server-side cursor
  paging (`src/ecom/extract.py`).
- Immutable Bronze batches with manifest + checksums, plus a quarantine envelope for
  invalid rows (`src/ecom/load.py`).
- Compare-and-swap checkpoint advance only after durable persistence.
- Crash recovery between batch publication and checkpoint commit.
- Idempotent load into `raw_stage` (reprocessing converges, no duplicate facts).
- Bounded, separately tracked backfills that never advance the normal checkpoint.
- dbt `silver.stg_orders`: one current version per `order_id`, with lineage and quality
  flags.
- Gold promotion gated on the exact dbt `manifest.json`/`run_results.json` pair; a failed
  candidate never replaces the certified view (`src/ecom/publish.py`).
- Candidate retention as an independent command (`src/ecom/retention.py`).
- dbt tests asserting Gold contract rules and Silver-to-Gold reconciliation.

### Order items + BRL commerce mart (Phase 2A, closed)

```text
Olist order_items CSV -> source.order_items (composite cursor, ADR-006)
  -> committed batch envelope -> Bronze/Quarantine Parquet
  -> raw_stage.order_items -> dbt silver.stg_order_items -> int_order_commerce
  -> versioned Gold candidate -> required tests -> certified Gold view
  (gold.mart_daily_commerce)
```

- `src/ecom/bootstrap_items.py`, `src/ecom/extract_items.py`, `src/ecom/load_items.py`:
  parallel, entity-specific modules (not a generic multi-entity framework) mirroring the
  orders pipeline, reusing `cursor.py`/`batchid.py`/`timez.py`/`db.py`.
- `source.order_items.source_cursor_key` is a Postgres generated column implementing
  ADR-006's padded composite key; `cursor.build_predicate` now takes an optional
  `key_column` (default `order_id`, unchanged for orders).
- `src/ecom/load.py` and `load_items.py` each filter `control.batch` by `entity_name`
  (fixed a real cross-contamination bug: the original `load.py` query had no entity
  filter and would have tried to load `order_items` Bronze into `raw_stage.orders` once a
  second entity existed).
- `src/ecom/publish.py` and `retention.py` are now parameterized by `--product` /
  a small `PRODUCTS` registry (two products: `mart_daily_order_fulfillment`,
  `mart_daily_commerce`); default remains `mart_daily_order_fulfillment` for backward
  compatibility.
- `extract_items.py` supports both incremental and `--run-mode backfill` extraction
  (ADR-002/ADR-006 bounded, auditable backfill requests, never advancing the normal
  checkpoint).
- dbt: `silver.stg_order_items`, `silver.int_order_commerce` (one row per `order_id`,
  items pre-aggregated), `gold_candidate.mart_daily_commerce__<id>` ->
  `gold.mart_daily_commerce`, with `assert_commerce_mart_metric_rules`,
  `assert_commerce_mart_reconciles_to_silver`, and `assert_no_orphan_order_items`
  (GOLD-COM-ORPHAN-001 — an order_item whose order_id is absent from `stg_orders` fails
  the build rather than being silently excluded, per `AGENTS.md` §6.8).
- Failure-injection tests for `order_items` (`tests/test_phase2a_items.py`): crash-after-
  publish recovery, checkpoint CAS conflict, bounded backfill, and breaking-operational-
  schema fail-closed — same coverage categories as the `orders` suite.
- Verified locally end-to-end (exact CI command sequence, fresh Docker volume): unit
  tests, full integration suite (40 tests total across the repo), dbt build baseline+final
  (23/23 each), both products published at baseline and final, final reconciliation
  passing. GMV spot-check: excludes freight and excludes the `canceled` order's item value
  (definitions in ADR-005; worked example in `docs/evidence/phase2a-closure.md`).
- Closure evidence: [`docs/evidence/phase2a-closure.md`](evidence/phase2a-closure.md).
- Remaining Phase 2A limitations (non-blocking, carried forward): no `mutate_items`
  equivalent CLI (incremental-update demos use direct test-only inserts); backfill mode
  untested against equal-timestamp ties at scale.

### Order payments + synthetic refunds (Phase 2B, closed)

```text
Olist order_payments CSV -> source.order_payments (composite cursor, ADR-006)
  -> committed batch envelope -> Bronze/Quarantine Parquet
  -> raw_stage.order_payments -> dbt silver.stg_order_payments
  -> silver.int_payment_reconciliation (diagnostic only)
```

- `src/ecom/bootstrap_payments.py`, `extract_payments.py` (incremental + backfill),
  `load_payments.py`: same entity-specific pattern as `*_items.py`. No business timestamp
  exists in this source (unlike `shipping_limit_date` for items); only simulator-owned
  `source_created_at`/`source_updated_at`.
- `silver.int_payment_reconciliation`: diagnostic model comparing `sum(payment_value)` to
  `price + freight_value` per order. Disagreement is **expected** (ADR-005) and is never a
  blocking test or a GMV input — it exists for inspection only.
- `assert_no_orphan_order_payments`: a payment whose `order_id` is absent from
  `stg_orders` fails the build (checked against `stg_orders` directly, not
  `int_order_commerce`, since an order can legitimately have payments without ever having
  items — 775 such orders exist in the full Olist dataset; that must stay visible, not be
  conflated with a true orphan).
- Failure-injection tests for `order_payments` (`tests/test_phase2b_payments.py`): same
  categories as `order_items` (crash recovery, CAS conflict, backfill, breaking schema).
- `src/ecom/generate_refunds.py`: deterministic synthetic refund generator, parallel to
  `ecom.mutate`. Olist has no refund signal; this is explicitly labeled synthetic
  everywhere (contract, mart, evidence). Defaults to refunding the lexicographically
  first unrefunded payment; `--order-id`/`--payment-sequential` target a specific one.
  Refuses to double-refund.
- `source.order_refunds` has a database `FOREIGN KEY (order_id, payment_sequential)` into
  `source.order_payments`; `refund_id` is a single opaque key (no ADR-006 composite
  cursor needed for this entity).
- `gold.mart_daily_refunds`: grained by refund date (`America/Santiago` conversion of
  `refunded_at`), **not** purchase date — never merge with `mart_daily_commerce`'s cohort
  without an explicit join. `mart_daily_commerce.gmv_brl` is never reduced by refunds;
  confirmed by direct query (generating a refund against a known order left that order's
  `gmv_brl` unchanged).
- `assert_refund_amount_within_payment`: a refund exceeding its payment's value fails the
  build (defense-in-depth re-check of the generator's own invariant).
- Verified locally end-to-end (exact CI sequence, fresh Docker volume): dbt build
  baseline+final 40/40 each; 51 tests passing total (18 unit + 32 integration + 1
  reconciliation); all three Gold products published at both stages.
- Closure evidence: [`docs/evidence/phase2b-closure.md`](evidence/phase2b-closure.md).
  The intermediate [`phase2b-payments-closure.md`](evidence/phase2b-payments-closure.md)
  is retained as historical record only.

## 3. Phase 1.1 full-dataset verification snapshot (2026-09-08)

```text
pytest tests/            33 passed
ruff check src tests     all checks passed
ruff format --check      20 files already formatted
dbt build                PASS=11 WARN=0 ERROR=0 SKIP=0 TOTAL=11
publish                  published mart_daily_order_fulfillment -> gold_candidate...phase1_1_final
retention                candidate retention complete

raw_stage.orders = 99,455   (retains historical versions)
silver.stg_orders = 99,442  (one current row per order)
gold sum(order_count) = 99,442
```

Full detail: [`docs/evidence/phase1_1-closure.md`](evidence/phase1_1-closure.md).
Treat [`docs/evidence/phase1-closure.md`](evidence/phase1-closure.md) and
[`docs/evidence/progress-report.md`](evidence/progress-report.md) as historical — their
evidence sections still show pre-1.1 numbers (28 passed / 7 dbt nodes) and have not been
refreshed.

The repository is public at
[`github.com/JpHernandezOrellana/ecom-data-platform`](https://github.com/JpHernandezOrellana/ecom-data-platform)
with GitHub Actions CI on every push/PR (§6a).

## 4. Non-negotiable invariants (do not break silently)

- Cursor ordering: `(source_updated_at, order_id)`, lower-exclusive / upper-inclusive,
  upper bound fixed from one stable snapshot (ADR-002).
- No cross-system "exactly once" claim — recoverable, idempotent, at-least-once protocol.
- Raw/Bronze history is immutable; never rewritten to simplify downstream code.
- Invalid rows are quarantined or fail closed — never silently dropped.
- Contract-breaking schema changes fail closed (ADR-003).
- Money uses fixed-precision decimal, never float.
- Timestamps: Olist naive timestamps = `America/Sao_Paulo`; canonical storage = UTC;
  reporting date = `America/Santiago`; ambiguous times use `fold=0`; nonexistent times are
  quarantined (`docs/metrics.md`).
- Gold grain: one row per purchase-date cohort in `gold.mart_daily_order_fulfillment`; it is
  not a delivery-event or state-change history (ADR-004).
- `gmv_brl` excludes freight and excludes `canceled`/`unavailable` orders; never relabel
  it "revenue"; never net refunds into it (ADR-005). `mart_daily_refunds` is a separate
  mart with its own date role (refund date, not purchase date) — never merge the two
  without an explicit join.
- `order_items`/`order_payments` cursor keys use the padded composite pattern
  (`order_id || ':' || lpad(<child_key>, 4, '0')`, a generated column) — never reimplement
  this ad hoc for a new composite-key entity without following ADR-006's pattern.
  `order_refunds` uses a plain single-column key (`refund_id`); not every new entity
  needs ADR-006's padding.
- `source.order_refunds` is entirely synthetic demo data (ADR-005) — never present it or
  anything derived from it as observed Olist history.
- No CLP columns exist yet; BRL ships alone until ADR-007 is implemented (Phase 2D).

## 5. Not implemented yet

- `customers` ingestion and the `customer_id` vs `customer_unique_id` distinction (Phase
  2C slice 2, design not started — ADR-008 "Deferred").
- Any seller-grained Gold mart; `sellers` is ingested and orphan-checked but not yet
  consumed by a certified metric.
- Geolocation canonicalization remains separately deferred; no implementation phase is
  assigned yet.
- BRL->CLP FX conversion (ADR-007 design accepted; implementation deferred to Phase 2D).
- No `mutate_items`/`mutate_payments`/`mutate_products`/`mutate_sellers`-equivalent CLI
  for any of these entities (`generate_refunds.py` doubles as both the refunds demo tool
  and the test fixture generator); incremental-update demos use direct test-only inserts.
- Concurrent-write guarantees during extraction; hard-delete capture (unchanged from
  Phase 1, applies to every entity ingested so far).
- Airflow, dashboard, cloud infra, CDC, distributed processing, agent/MCP write access.

CI (`.github/workflows/ci.yml`) now exercises `orders`, `order_items`, `order_payments`,
`order_refunds`, `products`, and `sellers` against synthetic fixtures, publishing all four
Gold products at baseline and final (§6a). It has not been validated against the full
Olist dataset for any entity.

## 6a. CI

`.github/workflows/ci.yml` runs on every PR and push to `main`: `uv sync --frozen`, Ruff
lint + format check, unit tests, then a full pipeline cycle (bootstrap orders -> extract
-> load -> dbt seed -> dbt build -> publish all four products -> integration tests ->
converge -> dbt build -> publish all four products -> reconciliation) against two
ephemeral PostgreSQL containers started via the existing `compose.yaml`. `order_items`,
`order_payments`, `order_refunds`, `products`, and `sellers` ingestion all happen inside
the integration pytest step (`tests/test_phase2a_items.py`,
`tests/test_phase2b_payments.py`, `tests/test_phase2b_refunds.py`,
`tests/test_phase2c_products_sellers.py`), not as separate CI steps; by the time the
"final" dbt build runs, their `raw_stage` tables have real rows, so `mart_daily_commerce`,
`mart_daily_refunds`, and `mart_daily_category_commerce`'s dbt tests run against real data
in the final candidate (the baseline candidate is trivially empty, same pattern as orders
before its first mutation). Bootstraps use small synthetic fixtures
(`tests/fixtures/orders_small.csv`, `tests/fixtures/order_items_small.csv`,
`tests/fixtures/order_payments_small.csv`, `tests/fixtures/products_small.csv`,
`tests/fixtures/sellers_small.csv`, with `--allow-unverified-input`; refunds have no
bootstrap fixture since they are purely generated), never the full Olist CSVs. `dbt seed`
loads the static `product_category_name_translation` reference table (ADR-008 — not
ingested through bootstrap/extract/load since it has no natural key mutation). Verified
locally end-to-end (the exact CI command sequence, run against local Docker) before being
committed.

## 6. What to read for a given task

| Task | Read |
|---|---|
| Understand overall design | `SDD.md` (relevant section only), this file |
| Touch ingestion/extraction/checkpoint | ADR-002, `contracts/source/operational_orders.v1.yaml`, `src/ecom/extract.py`, its tests |
| Touch bootstrap/contracts/quarantine | ADR-003, `contracts/source/olist_orders.v1.yaml`, `src/ecom/bootstrap.py`, `src/ecom/contracts.py` |
| Touch Silver/Gold/metrics | ADR-004, `docs/metrics.md`, `contracts/gold/mart_daily_order_fulfillment.v1.yaml`, `dbt/models/silver/`, `dbt/tests/` |
| Touch publish/retention | `src/ecom/publish.py`, `src/ecom/retention.py`, ADR-004 §publication |
| Run or operate the pipeline | `README.md` Phase 1, Phase 2A, and Phase 2B runbooks, as applicable |
| Touch `order_items`/commerce mart (Phase 2A) | ADR-005, ADR-006, §7a below, `src/ecom/*_items.py`, `dbt/models/intermediate/int_order_commerce.sql` |
| Touch `order_payments`/reconciliation (Phase 2B) | ADR-005, ADR-006, `src/ecom/*_payments.py`, `dbt/models/intermediate/int_payment_reconciliation.sql` |
| Touch synthetic refunds/`mart_daily_refunds` (Phase 2B) | ADR-005, `src/ecom/generate_refunds.py`, `src/ecom/*_refunds.py`, `dbt/models/gold_candidate/mart_daily_refunds.sql` |
| Touch `products`/`sellers`/category commerce mart (Phase 2C slice 1) | ADR-008, §7c below, `src/ecom/*_products.py`, `src/ecom/*_sellers.py`, `dbt/models/intermediate/int_order_items_category.sql` |
| Investigate a regression | `docs/evidence/*` (historical, read-only) |

Do not infer architecture from filenames alone, and do not re-read the entire repo for a
narrowly scoped task.

## 7. Resolved decisions (Phase 2 design)

- **GMV/AOV/freight/cancellation/refund semantics:** accepted in
  [ADR-005](adrs/ADR-005-commerce-metrics.md). GMV = `sum(order_items.price)`, freight
  excluded and reported separately; eligible orders exclude `canceled`/`unavailable`;
  refunds are not inferred from existing signals — a synthetic refund event source lands
  in Phase 2B, reported in a separate `mart_daily_refunds`, never netted into `gmv_brl`.
- **Composite-key cursor for `order_items`:** accepted in
  [ADR-006](adrs/ADR-006-composite-entity-cursor.md), extending ADR-002.
  `source_cursor_key = order_id || ':' || lpad(order_item_id, 4, '0')`; no
  `control.checkpoint`/`control.batch` schema change needed.
- **BRL->CLP FX source and policy:** accepted (design only) in
  [ADR-007](adrs/ADR-007-fx-brl-clp.md): BCB PTAX (BRL/USD, buy+sell average) crossed with
  SII Dólar Observado (CLP/USD) via USD; 7-day max carry-forward for missing days,
  fails closed beyond that; integer half-up rounding for CLP. Implementation deferred to
  Phase 2D — BRL ships first.
- Data contracts for `order_items` are accepted and implemented (§2).
- **Products/sellers dimensions and category commerce mart:** accepted in
  [ADR-008](adrs/ADR-008-category-seller-dimensions.md). Simple single-column keys reuse
  ADR-002 unchanged (no composite cursor); `product_category_name_translation` is a dbt
  seed, not an ingested entity; `mart_daily_category_commerce` reapplies ADR-005's
  eligibility rules at item grain and reconciles to `mart_daily_commerce.gmv_brl`.

Any future change to ingestion pattern, checkpoint semantics, storage format, warehouse
engine, orchestration, Gold grain, or metric semantics beyond what these ADRs cover
requires its own new/updated ADR before implementation (`AGENTS.md` §23).

## 7a. Phase 2A status (order items + BRL commerce mart) — closed 2026-10-05

Implemented, tested, and closed. Closure evidence:
[`docs/evidence/phase2a-closure.md`](evidence/phase2a-closure.md). Non-blocking items
carried forward into later phases:

1. No `mutate_items`-equivalent CLI exists; incremental-update demonstrations for items
   use direct test-only inserts rather than a reusable command.
2. Backfill mode for `order_items` has not been exercised against equal-timestamp ties
   at scale (the orders bootstrap deliberately creates many; the items fixture does not).

## 7b. Phase 2B status (payments + synthetic refunds) — closed 2026-10-05

Implemented, tested, and closed. Closure evidence:
[`docs/evidence/phase2b-closure.md`](evidence/phase2b-closure.md) (supersedes the
intermediate [`phase2b-payments-closure.md`](evidence/phase2b-payments-closure.md)).
Non-blocking items carried forward:

1. No `mutate_payments`-equivalent CLI; `ecom.generate_refunds` doubles as both the
   refunds demo tool and the test fixture generator for payments/refunds interplay.
2. Backfill mode for `order_payments`/`order_refunds` has not been exercised against
   equal-timestamp ties at scale.
3. `int_payment_reconciliation` has not been run against the full Olist dataset to
   confirm ADR-005's documented ~1.3% disagreement rate.
4. The refund generator always refunds 100% of a payment; no partial-refund modeling
   (accepted simplification for a demo fixture).

## 7c. Phase 2C slice 1 status (products + sellers + category commerce mart) — closed 2026-10-05

Implemented, tested, and closed. Closure evidence:
[`docs/evidence/phase2c-closure.md`](evidence/phase2c-closure.md). Non-blocking items
carried forward:

1. `customers` ingestion and the `customer_id`/`customer_unique_id` distinction are not
   part of this slice (ADR-008 "Deferred").
2. `sellers` is ingested and orphan-checked but has no seller-grained Gold metric yet.
3. Backfill mode for `products`/`sellers` has not been exercised against equal-timestamp
   ties at scale.
4. No `mutate_products`/`mutate_sellers`-equivalent CLI; incremental-update demos use
   direct test-only inserts.

## 8. Recommended next slice

Phase 2C slice 2: `customers` ingestion and the `customer_unique_id` vs `customer_id`
distinction (SDD §9.4), pending its own ADR per `AGENTS.md` §23 (new customer-history
semantics). No change to the Phase 2A/2B/2C-slice-1 monetary grain.

## 9. Keeping this file honest

Update this file whenever a phase closes, evidence is refreshed, or an open decision is
resolved. Precedence depends on the information type:

- this file is authoritative for current progress, the active phase, next work, and open
  limitations;
- the accepted SDD, ADRs, contracts, and metric glossary are authoritative for design,
  interfaces, and semantics;
- each dated evidence document is authoritative only for the execution it records.

A historical evidence snapshot never determines the current phase. When current progress
changes, update this file instead of rewriting historical evidence.
