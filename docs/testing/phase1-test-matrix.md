# Phase 1 Test Matrix

**Status:** Accepted  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Related SDD:** `SDD.md`, Sections 29 and 33

This matrix defines required evidence before implementation. Test filenames and framework-specific organization are implementation details, but every invariant below must remain covered.

## Cursor and extraction

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| CUR-001 | Unit | No checkpoint exists | Query has no lower predicate and uses the fixed inclusive upper tuple |
| CUR-002 | Unit | Row equals lower cursor | Row is excluded |
| CUR-003 | Unit | Row equals upper cursor | Row is included |
| CUR-004 | Unit | Multiple rows share one `source_updated_at` | Rows are ordered and paginated by `order_id` without loss |
| CUR-005 | Integration | Page boundary splits equal timestamps | Every eligible row is extracted exactly once in the logical batch |
| CUR-006 | Failure | `source_updated_at` or `order_id` is null | Entity fails before bounded extraction and checkpoint does not move |
| CUR-007 | Integration | Empty bounded window | Run records `no_op` and cursor does not change |
| CUR-008 | Unit | Existing order mutation | New `source_updated_at` is strictly later than the prior value |

## Bootstrap and timezone

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| BOOT-001 | Contract | Reviewed Olist orders header and hash | Input matches manifest and contract |
| BOOT-002 | Contract | Required column removed | Complete bootstrap fails closed |
| BOOT-003 | Quarantine | One malformed non-key timestamp below threshold | Row is preserved in bootstrap quarantine and accepted rows may load |
| BOOT-004 | Quarantine | Rejection count or rate exceeds threshold | Bootstrap fails after all rejected rows are durable |
| BOOT-005 | Idempotency | Equivalent bootstrap repeated | Operational state and generated source timestamps converge exactly |
| TIME-001 | Unit | Exact Sao Paulo local time | Correct UTC instant and `exact` resolution code |
| TIME-002 | Unit | Ambiguous Sao Paulo local time | Deterministic `fold=0` instant and `ambiguous_fold_0` flag |
| TIME-003 | Unit | Nonexistent Sao Paulo local time | Row is quarantined; no invented instant |
| TIME-004 | Unit | UTC purchase instant crosses Chilean date boundary | `reporting_date` uses `America/Santiago` correctly |
| TIME-005 | Unit | Duration spans timezone-offset change | Duration uses elapsed UTC seconds |

## Batch commit and checkpoint recovery

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| COMMIT-001 | Unit | Same normal cursor window and contract | Deterministic `batch_id` is unchanged |
| COMMIT-002 | Unit | Retry occurs on a later wall-clock date | Committed path remains unchanged because it uses `cursor_upper_date` |
| COMMIT-003 | Failure | Crash before manifest publication | Temporary directory cannot advance checkpoint |
| COMMIT-004 | Failure/recovery | Crash after atomic rename but before control transaction | Retry verifies the existing manifest, writes no second batch, and commits checkpoint |
| COMMIT-005 | Failure | Manifest checksum mismatch | Batch registration fails and checkpoint does not advance |
| COMMIT-006 | Concurrency | Stored checkpoint changed before compare-and-swap | Commit fails explicitly and does not report success |
| COMMIT-007 | Idempotency | Same committed batch loaded twice | `raw_stage` has one canonical source version and one logical load state |
| COMMIT-008 | Backfill | Backfill over normal cursor range | Backfill request state advances; normal checkpoint is unchanged |
| COMMIT-009 | Backfill | Same backfill request retried | `batch_id` remains stable |
| COMMIT-010 | Backfill | New authorized request for same range | New evidence `batch_id`; canonical state remains unchanged for identical versions |
| COMMIT-011 | Reconciliation | Compare committed manifests with control registrations | Every registered committed batch has one matching manifest and every recoverable committed manifest reaches a terminal control state |
| COMMIT-012 | Reconciliation | Compare loaded accepted versions with committed Bronze | `raw_stage` contains one canonical copy of every committed accepted source version selected for loading |

## Contracts and quarantine

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| DQ-001 | Contract | Unsupported isolated status below threshold | Row is durably quarantined and violation code is recorded |
| DQ-002 | Contract | Conflicting payload for one `(order_id, source_updated_at)` | Entity fails as a source-version invariant violation |
| DQ-003 | Quarantine | Same invalid payload retried | Deterministic `quarantine_id` prevents duplicate logical rejection evidence |
| DQ-004 | Quarantine | Extraction rejection threshold exceeded | Failed-attempt quarantine is durable and checkpoint remains unchanged |
| DQ-005 | Reconciliation | Successful batch with rejected rows | Extracted equals accepted plus rejected and manifest counts match readable Parquet |
| DQ-006 | Known anomaly | Delivered status without customer-delivery timestamp | Row remains visible with quality flag and is excluded from delivered metrics |
| DQ-007 | Known anomaly | Carrier handoff before approval | Source values remain unchanged and warning flag is visible |
| DQ-008 | Contract | Required operational source column removed or changed incompatibly | Extraction fails closed before batch publication and the normal checkpoint remains unchanged |

## Silver and Gold semantics

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| MODEL-001 | dbt | Multiple source versions for one order | `stg_orders` selects one deterministic latest version |
| MODEL-002 | dbt | Conflicting equal source versions | Build fails before arbitrary latest-row selection |
| MODEL-003 | Metric | All accepted statuses | Every structurally accepted latest order contributes to `order_count` |
| MODEL-004 | Metric | Delivered status with valid non-negative duration | Order contributes to delivered count and duration |
| MODEL-005 | Metric | Delivered status without delivery timestamp | Order does not contribute to delivered count and contributes to quality-issue count |
| MODEL-006 | Metric | Delivery equals estimate | Order is on time, not late |
| MODEL-007 | Metric | Delivery after estimate | Order contributes to late count and eligible denominator |
| MODEL-008 | Metric | Zero late-delivery eligible orders | Late-delivery rate is null |
| MODEL-009 | Metric | Zero valid delivered orders | Average delivery duration is null |
| MODEL-010 | Reconciliation | Aggregate Silver by reporting date | Gold order counts match eligible Silver cohorts |
| MODEL-011 | Grain | Candidate mart output | `reporting_date` is unique and non-null |

## Gold publication

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| PUB-001 | Integration | Candidate passes all required tests | Stable Gold view and publication metadata change in one transaction |
| PUB-002 | Failure | Candidate fails a required test | Stable Gold view continues to reference the previous certified candidate |
| PUB-003 | Retention | Candidate cleanup executes | Published candidate is never deleted |
| PUB-004 | Concurrency | Second publication starts while one is active | Only one publication flow proceeds |

## Operational evidence

| ID | Category | Scenario | Expected result |
|---|---|---|---|
| OBS-001 | Integration | Successful incremental run | Metadata contains run, attempt, batch, cursor, counts, files, tests, and status |
| OBS-002 | Failure | Retryable source connection error | Retry count and failure category are recorded; checkpoint does not move |
| OBS-003 | Security | Logs captured during run | No credentials, tokens, or unnecessary raw payloads appear |
| PERF-001 | Evidence | Healthy full Phase 1 run on reference allocation | Environment and duration are recorded; target is at most 15 minutes |

## Required test levels before Phase 1 acceptance

| Level | Requirement |
|---|---|
| Unit | All cursor, identifier, timezone, manifest, and metric calculations pass |
| Integration | Source-to-Bronze, quarantine, warehouse load, dbt, and promotion paths pass |
| Contract | Bootstrap, operational source, and Gold contracts pass |
| Data/dbt | Grain, uniqueness, accepted values, quality flags, and reconciliation pass |
| Idempotency | Equivalent rerun leaves canonical Silver and Gold unchanged |
| Failure/recovery | Crash after filesystem publication recovers without loss or duplicate committed batch |

No test may mock away the cursor, filesystem publication, checkpoint transaction, or Gold promotion behavior being demonstrated.
