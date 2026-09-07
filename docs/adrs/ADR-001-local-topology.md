# ADR-001: Local source and warehouse topology

**Status:** Accepted  
**Date:** 2026-09-06  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Decision scope:** Phase 1  
**Related SDD:** `SDD.md`, Sections 7, 11, and 33  

## Context

The portfolio must demonstrate that analytical workloads do not run against the operational source. It must also support independent source and warehouse failure tests while remaining inexpensive and understandable on a developer laptop.

The Phase 1 workload is approximately 99,441 historical orders plus small deterministic mutation batches. It does not require distributed storage or compute.

## Decision

Phase 1 uses Docker Compose with two PostgreSQL services:

- `source-postgres` contains only simulator-owned operational tables;
- `warehouse-postgres` contains control metadata, loaded raw data, Silver models, Gold candidates, and certified Gold views.

The services use separate credentials and persistent volumes. Extraction has a read-only source role after bootstrap and simulation writes complete. dbt has warehouse credentials only and cannot connect to the source.

Accepted and rejected batch evidence is stored as Parquet on a local mounted filesystem outside both databases.

Warehouse schemas are:

- `control`;
- `raw_stage`;
- `silver`;
- `gold_candidate`;
- `gold`.

Airflow is not part of Phase 1. Each stage is first implemented as an independently executable command.

## Alternatives considered

### One PostgreSQL service with two databases

Rejected for Phase 1 because a single service failure would affect both boundaries and weaken the warehouse-unavailable recovery demonstration. It would save some local resources but not enough to offset the loss of isolation evidence.

### One database with separate schemas

Rejected because credentials and resource boundaries would be easier to bypass accidentally, and analytical queries could reach operational tables directly.

### DuckDB as the warehouse

Deferred. DuckDB would be simpler for local analytics, but a separate PostgreSQL warehouse better demonstrates database roles, transactional control metadata, and a common junior Data Engineering stack.

### Cloud warehouse

Rejected for the local MVP because it introduces accounts, cost, networking, and credentials without a business requirement.

## Consequences

Positive consequences:

- explicit OLTP/OLAP separation;
- independent failure injection;
- clear credential boundaries;
- realistic PostgreSQL and dbt practice;
- no paid services.

Costs and limitations:

- two database services consume more memory than one;
- Compose configuration and health checks are required;
- local PostgreSQL is not a claim of cloud warehouse scale;
- local-disk disaster recovery remains outside the MVP.

## Reversal and migration path

The warehouse boundary is accessed through configuration and explicit interfaces. A later ADR may replace warehouse PostgreSQL with a cloud warehouse while retaining source contracts, Bronze evidence, metric definitions, and tests. The source and warehouse must remain logically isolated after migration.
