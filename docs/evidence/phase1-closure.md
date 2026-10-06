# Phase 1 Closure Evidence

**Status:** Closed
**Closed on:** 2026-09-07
**Scope:** Orders fulfillment vertical slice described in `SDD.md`, Section 33.

> Historical closure snapshot: results and future-phase statements reflect 2026-09-07.
> See [`docs/CURRENT_STATE.md`](../CURRENT_STATE.md) for current progress.

## Reference environment

- macOS 15.7.4; Apple M4; 16 GB RAM.
- Docker 29.7.2.
- PostgreSQL 16.15 containers for source and warehouse.
- Python 3.12 with locked `uv` dependencies.

## Clean-run evidence

The services started healthy with `docker compose up -d`. A clean rebuild used the
documented commands in the README:

| Stage | Result | Measured wall time |
|---|---:|---:|
| Bootstrap `olist_orders_dataset.csv` | 99,441 accepted, 0 rejected | 16 s |
| Initial bounded extract | 99,441 accepted, 0 rejected | 2 s |
| Initial Bronze-to-raw load | succeeded | 12 s |
| Deterministic mutation | 1 insert and 1 source-version update | < 1 s |
| Incremental extract | 2 accepted, 0 rejected | 1 s |
| Incremental load | succeeded | < 1 s |
| dbt build | 7 pass, 0 errors | 1 s |
| Gold publication | succeeded | 1 s |

The demonstrated healthy path is well within the 15-minute freshness target.

## Final reconciliation

After the full closure suite and final dbt build/publication:

| Layer | Count | Semantics |
|---|---:|---|
| `source.orders` | 99,442 | Current operational orders: Olist bootstrap plus deterministic insert. |
| Committed Bronze | 99,447 | Distinct accepted `(order_id, source_updated_at)` versions across committed manifests; physical backfill evidence may re-observe an existing version. |
| `raw_stage.orders` | 99,447 | Immutable canonical source versions; includes historical updates and replayed backfill versions. |
| `silver.stg_orders` | 99,442 | One latest deterministic version per `order_id`. |
| `gold.mart_daily_order_fulfillment` | 99,442 | Sum of `order_count`, one Chilean purchase-date cohort per row. |

`silver.stg_orders` retained 1,390 documented fulfillment-quality issues. They are
flagged rather than silently corrected.

The final normal checkpoint was `(2026-09-07T15:22:27+00:00,
00010242fe8c5a6d1ba2dd792cb16214)` at checkpoint version 6. Batch metadata records
the source, entity, run mode, cursor window, accepted/rejected counts, manifest path,
and load status for every committed batch.

## Verification

```text
uv run --extra dev pytest tests/     28 passed
uv run --extra dev ruff check src tests
All checks passed
uv run --extra dev ruff format --check src tests
18 files already formatted
PUBLICATION_ID=phase1-close uv run --project .. dbt build --profiles-dir .
PASS=7 WARN=0 ERROR=0 SKIP=0 TOTAL=7
uv run python -m ecom.publish --publication-id phase1-close --tests-passed
published mart_daily_order_fulfillment -> gold_candidate.mart_daily_order_fulfillment__phase1-close
```

The historical `--tests-passed` command above was replaced during Phase 1.1 with
artifact-verified publication; use the current README or `phase1_1-closure.md` for
the runnable command.

The test suite covers cursor boundaries, deterministic bootstrap and idempotency,
bootstrap quarantine thresholds, schema-breaking source failure without checkpoint
movement, crash-after-publication recovery, manifest checksum failure, checkpoint
compare-and-swap conflicts, idempotent load, backfill isolation, failed/concurrent
publication behavior, retryable source unavailability, no secret leakage in run output,

## Deferred Phase 2 gates

- Accepted monetary definitions for GMV, AOV, cancellation, and refunds.
- Authoritative BRL-to-CLP FX provider and fallback-day policy.
- Additional entity contracts: order items, payments, customers, products, and sellers.
- Airflow only after multiple independently executable entity paths are stable.
