# Current Project State

**Last updated:** 2026-10-04
**Current phase:** Phase 1.1 closed (hardened orders fulfillment vertical slice)
**Next phase:** Phase 2A design accepted (order items + BRL commerce mart); implementation not started

This document is the required entry point for any agent or contributor before touching
code. It does not replace the formal sources — it routes to them. Read this file and
`AGENTS.md` first; read everything else only as the task requires (see §6).

## 1. What this project is

A local-first, zero-paid-infrastructure portfolio Data Engineering platform demonstrating
reliable incremental ingestion, immutable raw evidence, explicit data contracts, quality
isolation (quarantine), dbt modeling, idempotency, and failure recovery. Source dataset:
Olist Brazilian e-commerce orders. See [`README.md`](../README.md) for the full pitch.

## 2. What exists today (implemented and verified)

One complete, closed vertical slice for **orders fulfillment**:

```text
Olist orders CSV -> source PostgreSQL -> bounded incremental extraction (cursor)
  -> committed batch envelope -> Bronze Parquet + Quarantine Parquet
  -> warehouse PostgreSQL (raw_stage) -> dbt Silver (stg_orders)
  -> versioned Gold candidate -> required tests -> certified Gold view
  (gold.mart_daily_order_fulfillment)
```

Concretely, the codebase implements:

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
- Phase 1/1.1 has no monetary metrics and no entities beyond orders.

## 5. Not implemented yet

- `order_items`, payments, customers, products, sellers, geolocation (design accepted,
  code not written — see §7a).
- GMV, AOV, synthetic refunds, BRL->CLP FX conversion (definitions accepted in ADR-005/
  ADR-006/ADR-007; no code yet).
- Concurrent-write guarantees during extraction; hard-delete capture.
- Airflow, dashboard, cloud infra, CDC, distributed processing, agent/MCP write access.

CI exists (see §6a) but only covers the orders slice against a synthetic fixture; it is
not yet validated against the full Olist dataset or extended to future entities.

## 6a. CI

`.github/workflows/ci.yml` runs on every PR and push to `main`: `uv sync --frozen`, Ruff
lint + format check, unit tests, then a full pipeline cycle (bootstrap -> extract -> load
-> dbt build -> publish -> integration tests -> converge -> dbt build -> publish ->
reconciliation) against two ephemeral PostgreSQL containers started via the existing
`compose.yaml`. It bootstraps from the small synthetic fixture
(`tests/fixtures/orders_small.csv`, with `--allow-unverified-input`), never the full Olist
CSV. Verified locally end-to-end before being committed.

## 6. What to read for a given task

| Task | Read |
|---|---|
| Understand overall design | `SDD.md` (relevant section only), this file |
| Touch ingestion/extraction/checkpoint | ADR-002, `contracts/source/operational_orders.v1.yaml`, `src/ecom/extract.py`, its tests |
| Touch bootstrap/contracts/quarantine | ADR-003, `contracts/source/olist_orders.v1.yaml`, `src/ecom/bootstrap.py`, `src/ecom/contracts.py` |
| Touch Silver/Gold/metrics | ADR-004, `docs/metrics.md`, `contracts/gold/mart_daily_order_fulfillment.v1.yaml`, `dbt/models/silver/`, `dbt/tests/` |
| Touch publish/retention | `src/ecom/publish.py`, `src/ecom/retention.py`, ADR-004 §publication |
| Run or operate the pipeline | `README.md` §Phase 1 runbook |
| Build `order_items`/commerce mart (Phase 2A) | ADR-005, ADR-006, §7a below, `src/ecom/extract.py` and `src/ecom/contracts.py` as the pattern to extend |
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
- Data contracts for each new entity, starting with `order_items`, remain to be written
  (next concrete step, §7a).

Any future change to ingestion pattern, checkpoint semantics, storage format, warehouse
engine, orchestration, Gold grain, or metric semantics beyond what these three ADRs cover
requires its own new/updated ADR before implementation (`AGENTS.md` §23).

## 7a. Phase 2A implementation plan (order items + BRL commerce mart)

Not yet built. Vertical slice, in order:

1. `contracts/source/olist_order_items.v1.yaml` and
   `contracts/source/operational_order_items.v1.yaml` (mirror the `orders` contracts;
   PK `(order_id, order_item_id)`, `price`/`freight_value` as Decimal).
2. `source.order_items` table + index on
   `(source_updated_at, order_id, order_item_id)` (ADR-006).
3. Extend `src/ecom/bootstrap.py`/`contracts.py`/`extract.py`/`load.py` to be
   entity-parameterized rather than hardcoded to `orders` (currently assumes
   `ENTITY = "orders"` throughout — this is the required refactor, not a rewrite).
4. `silver.stg_order_items`, then `int_order_commerce` (one row per `order_id`,
   items pre-aggregated to avoid multiplying AOV's denominator).
5. `gold_candidate.mart_daily_commerce__<publication_id>` -> `gold.mart_daily_commerce`
   (BRL only, ADR-005 metrics, same purchase-date cohort grain as
   `mart_daily_order_fulfillment`).
6. `contracts/gold/mart_daily_commerce.v1.yaml` and dbt tests mirroring ADR-004's pattern
   (metric rules + Silver-to-Gold reconciliation).
7. Tests: contract/bootstrap, cursor boundaries (including padding correctness for
   `order_item_id` 1 vs 10+), idempotent reload, reconciliation across layers — same
   categories as the existing `orders` suite.

## 8. Recommended next slice

`order_items` (Phase 2A), per §7a above — the design is accepted, implementation has not
started.

## 9. Keeping this file honest

Update this file whenever a phase closes, evidence is refreshed, or an open decision is
resolved. If this file and the evidence/ADRs disagree, the evidence/ADRs win — fix this
file, not your assumptions.
