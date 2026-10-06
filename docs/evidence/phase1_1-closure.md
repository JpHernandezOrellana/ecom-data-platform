# Phase 1.1 Closure Evidence

**Status:** Closed
**Closed on:** 2026-09-08
**Scope:** Hardening the accepted Phase 1 orders fulfillment slice without changing its
architecture, grain, or metric semantics.

> Historical closure snapshot: results and future-phase statements reflect 2026-09-08.
> See [`docs/CURRENT_STATE.md`](../CURRENT_STATE.md) for current progress.

## Closed alignment gaps

- Bootstrap reads its YAML contract, validates the pinned source checksum, and fails the
  complete bootstrap on duplicate accepted order keys.
- Operational extraction validates contractual identifiers and timestamp provenance, reads
  through a server-side cursor in `BATCH_PAGE_SIZE` pages, and preserves provenance in
  Bronze and raw stage.
- Bronze loading verifies manifest checksums, Parquet readability, and row counts before
  recording a batch as loaded.
- Backfills have a separately persisted bounded request, reason, state, and batch ID; they
  do not advance the normal checkpoint.
- Gold promotion verifies dbt `manifest.json` and `run_results.json` for the exact candidate,
  retains explicit Gold-view columns, and records the verification artifact paths.
- dbt now directly tests the Gold contract rules and Silver-to-Gold reconciliation.
- Candidate retention is an independently executable command that preserves the candidate
  referenced by the certified Gold view.

## Verification

The local Docker source and warehouse services were healthy. The completed verification on
the documented local environment produced:

```text
uv run --extra dev pytest tests/     33 passed
uv run --extra dev ruff check src tests
All checks passed
uv run --extra dev ruff format --check src tests
20 files already formatted
PUBLICATION_ID=phase1_1_final uv run --project . dbt build --project-dir dbt --profiles-dir dbt
PASS=11 WARN=0 ERROR=0 SKIP=0 TOTAL=11
uv run python -m ecom.publish --publication-id phase1_1_final \
  --test-results dbt/target/run_results.json --dbt-manifest dbt/target/manifest.json
published mart_daily_order_fulfillment -> gold_candidate.mart_daily_order_fulfillment__phase1_1_final
uv run python -m ecom.retention
candidate retention complete
```

The final certified publication was `published`. The post-suite query reported
`raw_stage.orders=99,455`, `silver.stg_orders=99,442`, and certified Gold
`sum(order_count)=99,442`. Raw stage retains source versions while Silver and Gold retain
their documented current-order and purchase-cohort grains.

## Phase 2 gates

Phase 2 remains unstarted. Its entry gates are unchanged: accepted monetary semantics,
an authoritative BRL-to-CLP source and fallback policy, and contracts for each added
entity beginning with order items.
