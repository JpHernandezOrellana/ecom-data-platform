# ADR-009: Airflow orchestration of the existing pipeline stages

**Status:** Accepted
**Date:** 2026-10-06
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-06
**Decision scope:** Local orchestration of the already-independent extract/load/dbt/publish
commands across all entities
**Implementation evidence:** `docs/evidence/airflow-orchestration-closure.md`
**Related SDD:** `SDD.md` §30 (Orchestration), §33 Roadmap ("Airflow after tasks work
independently")
**Related ADRs:** ADR-001 (topology, unchanged), ADR-002/006/008 (per-entity ingestion,
unchanged), ADR-004 (publication protocol, unchanged)

## Context

`SDD.md` §30 gates Airflow explicitly: *"Airflow is not part of Phase 1. Each pipeline
stage must first exist as an independently executable and tested command... When Phase 2
has multiple stable dependent stages, one Airflow DAG may orchestrate."* That condition is
now met: eight entities (`orders`, `order_items`, `order_payments`, `order_refunds`,
`products`, `sellers`, `customers`, FX rates) each have independently executable,
individually tested `extract_*`/`load_*`/`fetch_fx_rates` commands, a shared dbt project,
and four `publish` targets. Today an operator runs roughly 20 commands by hand per the
README runbooks. The existing pipeline therefore has a concrete need for a dependency
graph, retries, and one-command execution. This ADR is scoped narrowly to orchestration
only.

## Decision

### What the DAG orchestrates

One DAG, `ecom_pipeline`, reproducing the exact conceptual flow in `SDD.md` §30:

```text
extract_<entity> (parallel, per entity) -> load_<entity> (parallel, per entity)
        |
fetch_fx_rates (parallel with the above)
        |
dbt seed -> dbt build (one shared project, all Silver/Gold candidates)
        |
publish_<product> (parallel, per Gold product; each reads the same run_results.json/
manifest.json produced by the single dbt build)
```

`dbt build` depends on **every** `load_*` task and `fetch_fx_rates` succeeding
(`trigger_rule=all_success`): a failed extract/load for any one entity blocks the shared
build rather than letting Gold candidates build from partially stale data. Each `publish_*` task is
independent of the others (one product's publish failure does not block another's),
mirroring how `publish.py` already treats products independently.

### What the DAG does **not** orchestrate

- **Bootstrap** (`bootstrap*.py`) — a one-time historical-data-load action, not a
  recurring pipeline stage. Running it is an explicit manual/CI step, as today.
- **`scripts/create_source_reader.sh`** — a one-time host-side setup step (it shells out
  to `docker compose exec`, which requires host Docker CLI access the Airflow container
  does not have). The DAG assumes the reader role already exists, same precondition as
  running `extract.py` manually today.
- **`ecom.mutate`/`ecom.generate_refunds`** — demo/test data generators, not production
  pipeline stages.
- **`ecom.retention`** — candidate retention is a separate, independently schedulable
  concern; not added to this DAG to keep its scope narrow. Implemented as its own
  `ecom_retention` DAG (one task, `schedule=None`, same manual-trigger posture) rather
  than folded into `ecom_pipeline` — exactly the reversal/migration path anticipated
  below, exercised rather than left purely theoretical.
- Transformation logic itself. Per `SDD.md` §30: *"Airflow does not contain
  transformation logic or serve as the only checkpoint store."* Every task is a thin
  wrapper that shells out to an existing, independently tested CLI command; `control.*`
  in the warehouse remains the actual checkpoint/batch state, not Airflow's metadata DB.

### Local topology

Airflow runs as one additional Docker Compose service (`airflow`), using the official
`apache/airflow` image with a thin custom layer that installs `uv` (so tasks can run
`uv run python -m ecom.X` against the same project checkout, mounted read-write into the
container). It uses `SequentialExecutor` with a local SQLite metadata database
(`airflow standalone` mode) — this is Airflow's own documented local/dev configuration,
appropriate here since this project has no concurrent-task-execution requirement and the
zero-paid-infrastructure constraint rules out a managed Airflow metadata Postgres. The
Airflow metadata database is entirely separate from, and has no bearing on, this
project's own `control.*` checkpoint tables.

The Airflow container joins the existing Compose network and reaches
`source-postgres`/`warehouse-postgres` by service name on their internal port 5432 — not
through the host-mapped ports used by host-side tooling (`SOURCE_PORT`/`WAREHOUSE_PORT`).
This is a distinct, container-network set of DSNs from the host `.env`, not a new secret
or credential scheme.

### Scheduling

The DAG is defined with `schedule=None` (manually triggerable only), matching this
project's existing "manually_triggerable" freshness posture (`docs/metrics.md`,
contracts' `freshness.cadence`). A daily schedule can be enabled later by changing one
line once there is a concrete freshness requirement to test against — not speculatively
enabled now.

## Alternatives considered

### A managed/cloud orchestrator (MWAA, Cloud Composer, Astronomer)

Rejected: violates the zero-paid-infrastructure constraint and introduces cloud
credentials without a business requirement.

### Orchestrate inside a single Python script (no orchestrator)

Rejected: already effectively what today's README runbooks do by hand; it does not
demonstrate dependency-graph orchestration, retries, or a scheduler, which is the actual
capability this ADR is meant to add evidence for.

### Prefect or Dagster instead of Airflow

Rejected: Airflow is the orchestrator named by `SDD.md` §30 and
`ARCHITECTURE_BIBLE.md` for this kind of batch DAG; introducing a second orchestrator
would add an unnecessary architectural choice.

### LocalExecutor with a dedicated Airflow metadata Postgres

Rejected for now: adds a third Postgres service for no demonstrated need at this scale
(two entities' worth of sequential tasks run in well under a second each).
`SequentialExecutor` is explicitly documented by Airflow as intended for this kind of
local/testing use.

### Have Airflow tasks call Python functions directly (PythonOperator) instead of shelling out

Rejected: every existing command is a CLI entry point designed to be independently
runnable and tested outside Airflow; shelling out via `BashOperator` preserves that
property rather than coupling task logic to Airflow's import path.

## Consequences

Positive:

- the full pipeline becomes one-command-triggerable instead of ~20 manual steps;
- the dependency graph (extract/load per entity -> shared build -> independent publishes)
  is now an explicit, inspectable artifact instead of implicit runbook ordering;
- no change to any existing ingestion/transformation/publication code — every task is a
  thin wrapper around an already-accepted, already-tested command.

Costs and limitations:

- a new, fairly heavy local dependency (the Airflow image, ~2 GB) for a batch workload
  that does not yet need a scheduler's concurrency/retry machinery;
- `SequentialExecutor`/SQLite is explicitly a local/dev configuration, not a claim of
  production Airflow operational maturity;
- the DAG is not exercised by the automated CI pipeline (CI continues to run the
  individual commands directly, as today) — it is a manually-verified, documented local
  capability, not a new automated test surface. Adding Airflow to CI is a separate,
  explicitly out-of-scope future decision given the added CI runtime/complexity cost.

## Reversal and migration path

The DAG only shells out to existing commands; removing it (or replacing it with a
different orchestrator later) requires no change to `src/ecom/*`, `dbt/*`, or any
contract. Reverting is deleting the `airflow` Compose service and `dags/` directory.
