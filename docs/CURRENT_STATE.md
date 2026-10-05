# Current Project State

**Last updated:** 2026-10-05
**Current phase:** Phase 2A closed (order items + BRL commerce mart)
**Next phase:** Phase 2B (payments + synthetic refunds)

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
  passing. GMV spot-check: excludes freight, excludes the `canceled` order's item value
  (worked example in ADR-005 and `docs/evidence/phase2a-closure.md`).
- Closure evidence: [`docs/evidence/phase2a-closure.md`](evidence/phase2a-closure.md).
- Remaining Phase 2A limitations (non-blocking, carried forward): no `mutate_items`
  equivalent CLI (incremental-update demos use direct test-only inserts); backfill mode
  untested against equal-timestamp ties at scale.

## 3. Latest verification (Phase 1.1 closure, 2026-09-08)

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
  it "revenue"; never net refunds into it (ADR-005).
- `order_items` cursor key is `order_id || ':' || lpad(order_item_id, 4, '0')`
  (`source.order_items.source_cursor_key`, a generated column) — never reimplement this
  padding ad hoc for a new composite-key entity without following ADR-006's pattern.
- No CLP columns exist yet; BRL ships alone until ADR-007 is implemented (Phase 2D).

## 5. Not implemented yet

- Payments, customers, products, sellers, geolocation (Phase 2B/2C, design not started
  beyond the refund-handling sketch in ADR-005).
- Synthetic refunds and `mart_daily_refunds` (ADR-005, Phase 2B — order_items/GMV ship
  first, refunds come after payments).
- BRL->CLP FX conversion (ADR-007 design accepted; implementation deferred to Phase 2D).
- Backfill mode for `order_items` (`extract_items.py` only supports incremental
  extraction; `orders`-style `--run-mode backfill` does not exist yet for items). Crash
  recovery, checkpoint CAS conflict, and breaking-schema fail-closed are now covered
  (`tests/test_phase2a_items.py`).
- Concurrent-write guarantees during extraction; hard-delete capture (unchanged from
  Phase 1, applies to `order_items` too).
- Airflow, dashboard, cloud infra, CDC, distributed processing, agent/MCP write access.

CI (`.github/workflows/ci.yml`) now exercises both `orders` and `order_items` against
synthetic fixtures, including both products' publish step (§6a). It has not been
validated against the full Olist dataset for either entity.

## 6a. CI

`.github/workflows/ci.yml` runs on every PR and push to `main`: `uv sync --frozen`, Ruff
lint + format check, unit tests, then a full pipeline cycle (bootstrap orders -> extract
-> load -> dbt build -> publish both products -> integration tests -> converge -> dbt
build -> publish both products -> reconciliation) against two ephemeral PostgreSQL
containers started via the existing `compose.yaml`. `order_items` bootstrap/extract/load
happens inside the integration pytest step (`tests/test_phase2a_items.py`), not as
separate CI steps; by the time the "final" dbt build runs, `raw_stage.order_items` has
real rows, so `mart_daily_commerce`'s dbt tests run against real data in the final
candidate (the baseline candidate is trivially empty, same pattern as orders before its
first mutation). Bootstraps use small synthetic fixtures
(`tests/fixtures/orders_small.csv`, `tests/fixtures/order_items_small.csv`, with
`--allow-unverified-input`), never the full Olist CSVs. Verified locally end-to-end
(the exact CI command sequence, run against local Docker) before being committed.

## 6. What to read for a given task

| Task | Read |
|---|---|
| Understand overall design | `SDD.md` (relevant section only), this file |
| Touch ingestion/extraction/checkpoint | ADR-002, `contracts/source/operational_orders.v1.yaml`, `src/ecom/extract.py`, its tests |
| Touch bootstrap/contracts/quarantine | ADR-003, `contracts/source/olist_orders.v1.yaml`, `src/ecom/bootstrap.py`, `src/ecom/contracts.py` |
| Touch Silver/Gold/metrics | ADR-004, `docs/metrics.md`, `contracts/gold/mart_daily_order_fulfillment.v1.yaml`, `dbt/models/silver/`, `dbt/tests/` |
| Touch publish/retention | `src/ecom/publish.py`, `src/ecom/retention.py`, ADR-004 §publication |
| Run or operate the pipeline | `README.md` §Phase 1 runbook |
| Touch `order_items`/commerce mart (Phase 2A) | ADR-005, ADR-006, §7a below, `src/ecom/*_items.py`, `dbt/models/intermediate/int_order_commerce.sql` |
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

Any future change to ingestion pattern, checkpoint semantics, storage format, warehouse
engine, orchestration, Gold grain, or metric semantics beyond what these three ADRs cover
requires its own new/updated ADR before implementation (`AGENTS.md` §23).

## 7a. Phase 2A status (order items + BRL commerce mart) — closed 2026-10-05

Implemented, tested, and closed. Closure evidence:
[`docs/evidence/phase2a-closure.md`](evidence/phase2a-closure.md). Non-blocking items
carried forward into later phases:

1. No `mutate_items`-equivalent CLI exists; incremental-update demonstrations for items
   use direct test-only inserts rather than a reusable command.
2. Backfill mode for `order_items` has not been exercised against equal-timestamp ties
   at scale (the orders bootstrap deliberately creates many; the items fixture does not).

## 8. Recommended next slice

Phase 2B: `order_payments` contract + ingestion, payment reconciliation diagnostics
against `price + freight_value`, and the synthetic refund event generator feeding
`mart_daily_refunds` (ADR-005).

## 9. Keeping this file honest

Update this file whenever a phase closes, evidence is refreshed, or an open decision is
resolved. If this file and the evidence/ADRs disagree, the evidence/ADRs win — fix this
file, not your assumptions.
