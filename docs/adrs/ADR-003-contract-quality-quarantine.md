# ADR-003: Contracts, quality severity, and quarantine

**Status:** Accepted  
**Date:** 2026-09-06  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Decision scope:** Phase 1  
**Related SDD:** `SDD.md`, Sections 7, 9, 16, 21, and 22  

## Context

The Olist orders file is structurally regular but contains real business-quality anomalies. Examples include delivered orders without a customer-delivery timestamp and inconsistent lifecycle ordering. Rejecting the entire historical dataset would hide realistic quality behavior, while silently correcting or ignoring anomalies would make certified metrics untrustworthy.

Bootstrap CSV validation and operational PostgreSQL extraction are separate boundaries. They have different possible failures and must not share ambiguous handling.

## Decision

### Contract representation

Phase 1 uses version-controlled repository-owned YAML contracts:

- `contracts/source/olist_orders.v1.yaml` for the bootstrap CSV;
- `contracts/source/operational_orders.v1.yaml` for incremental extraction;
- `contracts/gold/mart_daily_order_fulfillment.v1.yaml` for the consumer product.

dbt model contracts supplement these files where applicable. ODCS tooling is deferred.

### Bootstrap validation

Missing or incompatible required columns fail the complete bootstrap input. Individual malformed records are written to bootstrap quarantine before accepted rows enter PostgreSQL.

### Operational extraction validation

Database types protect basic storage, while the ingestion contract enforces stricter identifier, status, timestamp-provenance, and source-version rules. Dedicated test schemas simulate upstream contract violations without weakening normal source constraints.

### Severity policy

Structural failures stop the affected input or entity. These include missing required columns, incompatible types, null cursor components, source-version payload conflicts, and manifest mismatches.

Isolated invalid values are quarantined when the row can be identified and preserved safely. Examples include malformed non-null identifiers, unsupported status values, and timestamps that cannot be parsed or localized.

Known business anomalies remain visible as Silver quality flags. They are never silently corrected. Metric contracts determine whether a flagged row is eligible for a specific metric.

### Rejection threshold

A bootstrap or extraction batch may succeed only when:

```text
rejected_count <= 10
and rejected_count / evaluated_count <= 1 percent
```

`evaluated_count` is accepted plus rejected rows. A zero-row batch has a zero rejection rate. Exceeding either threshold fails the operation. Extraction does not advance its checkpoint, and all rejected evidence remains durable.

### Timezone resolution

Naive Olist timestamps are interpreted as `America/Sao_Paulo`. Ambiguous timestamps select IANA `fold=0` and receive a quality flag. Nonexistent local timestamps are quarantined. Original timestamp text and the resolution code are preserved.

## Alternatives considered

### Fail on every business anomaly

Rejected because known source anomalies would prevent the historical slice from producing any analytical result and would confuse source quality with structural contract integrity.

### Drop invalid rows

Rejected because it violates no-silent-loss and prevents inspection or correction.

### Accept all invalid rows into Bronze

Rejected because Bronze is defined as accepted operational-source evidence. Quarantine preserves invalid evidence under a separate logical dataset in the same committed envelope when the batch is allowed to continue.

### Introduce an external contract platform

Rejected because YAML plus deterministic validation is sufficient for the vertical slice and avoids an unnecessary dependency.

### Infer ambiguous timezone offsets

Rejected because the source does not contain enough evidence. A deterministic documented assumption is more honest.

## Consequences

Positive consequences:

- breaking changes fail closed;
- individual invalid rows remain inspectable;
- known source anomalies become visible portfolio evidence;
- Gold metrics use explicit eligibility instead of hidden correction;
- timezone conversion is deterministic.

Costs and limitations:

- rejected-row thresholds are project policy rather than source guarantees;
- ambiguous historical timestamps retain one hour of uncertainty;
- contracts and quality rules must evolve together;
- corrected operational rows require a later `source_updated_at`.

## Reversal and migration path

Contract documents can later map to ODCS or another standard after a separate evaluation. Threshold or severity changes require a contract version and synchronized SDD/ADR review when behavior changes materially.
