# Progress Report

**Updated:** 2026-09-08
**Current stage:** Phase 1.1 closed; Phase 2 design not started
**Authoritative design:** `SDD.md`

## Phase 1 status

The orders fulfillment vertical slice is closed. It provides a deterministic
orders bootstrap, bounded incremental extraction, immutable Bronze and
quarantine evidence, checkpoint recovery, idempotent raw loading, Silver and
Gold dbt models, and candidate-to-certified Gold publication.

The closure scope and the Phase 1 acceptance criteria are defined in
`SDD.md`, Section 33. Detailed execution evidence is in
`docs/evidence/phase1-closure.md`.

Phase 1.1 closed the identified design-alignment gaps. The current implementation
executes YAML-derived boundary validation, manifest verification, server-side extraction
pages, provenance-preserving Bronze loads, fail-closed Parquet validation, auditable
backfill requests, artifact-verified Gold promotion, direct Gold contract tests, and
candidate retention. Evidence is in `docs/evidence/phase1_1-closure.md`.

## Reconciliation snapshot

The closure run reconciled the layers using their documented grains:

| Layer | Count | Documented semantic |
|---|---:|---|
| `source.orders` | 99,442 | Current operational orders. |
| Committed Bronze | 99,447 | Distinct accepted source versions across committed manifests. |
| `raw_stage.orders` | 99,447 | One canonical copy of each accepted source version. |
| `silver.stg_orders` | 99,442 | One latest source version per order. |
| `gold.mart_daily_order_fulfillment` | 99,442 | Sum of purchase-date cohort `order_count`. |

Bronze and raw-stage counts exceed the source and Silver counts because they
preserve historical versions. A separately authorized backfill can retain
physical evidence of an already observed version; it does not create another
canonical raw-stage version.

## Verification

The closure evidence records a clean run, `28 passed`, Ruff checks, and a dbt
build with seven passing nodes. On 2026-09-07, the local verification repeated:

```bash
docker compose up -d
set -a; source .env; set +a
uv run --extra dev pytest tests/
uv run --extra dev ruff check src tests
uv run --extra dev ruff format --check src tests
cd dbt
PUBLICATION_ID=phase1-closure-verify uv run --project .. dbt build --profiles-dir .
```

Results: source and warehouse services healthy; `28 passed`; Ruff clean and
formatted; dbt `PASS=7 WARN=0 ERROR=0 SKIP=0 TOTAL=7`.

The documented `scripts/create_source_reader.sh` was also exercised against
the local source. It creates or updates the role idempotently, enables reads
from `source.orders`, and rejects a `DELETE` attempt.

## Deferred work

The following work is intentionally outside Phase 1 and does not reopen its
acceptance:

- automated contract validation (basic CI itself now exists — see
  `docs/CURRENT_STATE.md` §6a);
- candidate retention automation and a backfill operator CLI;
- orchestration with Airflow;
- dashboarding, cloud, CDC, distributed processing, and agent access.

## Phase 2 entry gates

**Update (2026-10-04):** gates 1 and 2 are now resolved — see
`docs/CURRENT_STATE.md` §7 and ADR-005/ADR-006/ADR-007. This section is kept for
historical context; `docs/CURRENT_STATE.md` is authoritative for current status.

No Phase 2 monetary model should be implemented until these decisions are
accepted and represented in the relevant ADRs, contracts, metrics, and tests:

1. GMV, AOV, cancellation, and refund semantics. — **Resolved:** ADR-005.
2. An authoritative historical BRL-to-CLP source and a fallback-day policy. —
   **Resolved (design):** ADR-007; implementation deferred to Phase 2D.
3. Contracts for each added source entity, beginning with order items. —
   **Still open**, tracked as the next concrete step in
   `docs/CURRENT_STATE.md` §7a.

The recommended next vertical slice is order items, because it establishes the
item-level grain required before GMV or AOV can be defined correctly.
