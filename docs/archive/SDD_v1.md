# Software Design Document (SDD)
## E-commerce Data Platform — Local-First Portfolio Project

**Document version:** 0.1  
**Project stage:** architecture/design only  
**Implementation status:** not started  
**Cost objective:** zero paid infrastructure for the initial implementation  
**Primary objective:** build a credible, interview-ready Data Engineering project that behaves like a small production data platform rather than a tutorial notebook.

---

# 1. Executive summary

This project will simulate the data platform of a small-to-medium e-commerce company.

The platform will ingest historical commercial data plus newly generated operational transactions, preserve raw history, validate and normalize records, create analytical models, and expose trustworthy marts for business analysis.

The initial system is deliberately **local-first** and avoids unnecessary distributed infrastructure. It is designed to demonstrate the engineering capabilities expected from an entry/junior Data Engineer:

- Python;
- SQL;
- PostgreSQL;
- incremental ingestion;
- idempotency;
- data contracts;
- Parquet;
- dbt;
- orchestration;
- Docker;
- data quality;
- dimensional modeling;
- logging/observability;
- testing;
- CI-ready structure;
- architectural documentation.

Future phases may add GCP/BigQuery, Terraform, CDC, Kafka and agentic analytics, but none are required in the MVP.

---

# 2. Portfolio narrative

The project should be explainable in an interview as:

> An e-commerce company has operational data spread across orders, customers, products, sellers, payments and shipping. Analytical workloads must not query the transactional system directly. I designed a local-first data platform that incrementally extracts changes, preserves raw data, enforces contracts and data quality, builds modeled layers and business marts, and can be safely replayed without duplicating facts.

The project must demonstrate **engineering judgment**, not maximum tool count.

---

# 3. Business problem

Operational e-commerce systems optimize for serving transactions.

The business requires trustworthy analytical answers such as:

- How much revenue was generated each day?
- Which products and sellers produce the most revenue?
- What is average order value?
- How many orders are delivered late?
- How long does fulfillment take?
- What proportion of orders are canceled?
- How do payment methods differ?
- Which regions generate the most demand?

Running those analytics directly on the operational database creates:

- coupling;
- performance risk;
- inconsistent metric definitions;
- limited historical reproducibility;
- weak data quality control.

The platform creates an analytical boundary.

---

# 4. Jobs to be done

## JTBD-1 — Reliable ingestion
As a data engineer, I need new and modified operational records to be ingested without repeatedly rebuilding all history.

## JTBD-2 — Replay
As a data engineer, I need to rerun a failed date/window without creating duplicate business facts.

## JTBD-3 — Quality isolation
As a data consumer, I need invalid data to be prevented from contaminating certified analytical tables.

## JTBD-4 — Consistent business metrics
As an analyst, I need revenue, order count, delivery delay and related metrics to have one documented definition.

## JTBD-5 — Traceability
As an operator, I need to determine which run processed a record/window and why a run failed.

## JTBD-6 — Local reproducibility
As a reviewer/recruiter, I need to be able to understand and reproduce the architecture without paid cloud infrastructure.

---

# 5. Goals

## G1
Create an end-to-end batch data pipeline representing a realistic e-commerce workload.

## G2
Separate operational and analytical workloads.

## G3
Support incremental ingestion.

## G4
Guarantee idempotent re-execution for the same ingestion window.

## G5
Preserve raw history in an immutable/append-only representation.

## G6
Implement data contracts and quality gates.

## G7
Create reusable Silver models and certified Gold marts.

## G8
Orchestrate the workflow with explicit dependencies and failure behavior.

## G9
Produce structured run metadata and logs.

## G10
Make the repository understandable without oral explanation.

## G11
Use only free/local infrastructure for the first complete version.

## G12
Leave clean migration paths toward GCP, CDC and agentic consumption.

---

# 6. Non-goals for MVP

The MVP will **not** attempt to demonstrate:

- Kubernetes;
- Kafka;
- Spark;
- Flink;
- microservices;
- multi-cloud;
- real-time streaming;
- production-grade IAM infrastructure;
- a full data catalog;
- an enterprise semantic-layer product;
- autonomous AI writes;
- machine learning.

These can be introduced in later phases only when a new requirement justifies them.

---

# 7. Constraints

- No paid infrastructure required.
- Must run locally using containers and/or local processes.
- Resource consumption must remain appropriate for a developer laptop.
- Dependencies must be open source or have a usable free local edition.
- All runtime dependencies must be pinned/locked.
- No secrets committed to the repository.
- Source and warehouse must be logically separated.
- Architecture must remain understandable to a junior engineer.
- No code implementation before the SDD is accepted.

---

# 8. Source data strategy

## 8.1 Historical bootstrap

Use the public Brazilian E-Commerce/Olist dataset as historical seed data.

Useful source entities include:

- customers;
- orders;
- order items;
- products;
- sellers;
- payments;
- reviews;
- geolocation/category metadata where useful.

The dataset is historical and will be treated as the initial state/bootstrap.

## 8.2 Continuing operational activity

A deterministic synthetic transaction generator will later create new e-commerce activity after the historical bootstrap.

The generator is a **source-system simulator**, not part of the analytical transformations.

It should eventually support:

- new customers;
- new orders;
- order items;
- payments;
- order status transitions;
- deliveries;
- cancellations;
- controlled invalid records for test scenarios.

The generator must be seedable so scenarios can be reproduced.

## 8.3 Why this hybrid approach

Historical real-world data gives realistic distributions and relationships.

Synthetic incremental activity makes it possible to test:

- incremental extraction;
- updates;
- late-arriving data;
- invalid records;
- retries;
- idempotency;
- state transitions.

---

# 9. Logical system boundaries

## Operational source
A PostgreSQL database representing the e-commerce application.

## Ingestion application
Python processes responsible for extracting source changes and persisting raw batches.

## Raw/Bronze
Parquet files representing accepted source extracts with ingestion metadata.

## Analytical warehouse
A separate PostgreSQL database or logical warehouse instance used for Silver/Gold analytics.

## Transformation layer
dbt models.

## Orchestration
Airflow in the first orchestrated phase.

## Quality/quarantine
Explicit invalid-record store plus dbt/data validation tests.

## Observability
Structured logs and run metadata.

---

# 10. High-level architecture

```text
Historical Olist data
        |
        v
Operational PostgreSQL  <--- future deterministic transaction simulator
        |
        | incremental extraction
        v
Python ingestion
        |
        +------ contract/schema validation
        |                 |
        | valid           | invalid
        v                 v
Bronze / Parquet      Quarantine
        |
        v
Warehouse PostgreSQL
        |
        v
dbt staging / Silver
        |
        +------ dbt quality gates
        |
        v
dbt Gold / marts
        |
        v
Analytics / optional dashboard

Airflow orchestrates the scheduled execution.

Structured run metadata, logging and test evidence cross-cut the pipeline.
```

---

# 11. Processing model

## MVP default
Scheduled batch.

Suggested conceptual cadence:
- daily batch for normal portfolio operation;
- manually triggerable runs for development/backfills.

Cadence itself is configurable and is not a data-model assumption.

## Why not streaming
There is no business requirement for sub-second or sub-minute freshness in the MVP.

Adding Kafka would increase operational complexity without improving the core learning objective.

---

# 12. Source operational model

The exact DDL is implementation work and is intentionally excluded here.

Conceptual entities:

## customer
- customer_id
- external/source identifiers
- location attributes
- created_at
- updated_at

## seller
- seller_id
- location attributes
- created_at
- updated_at

## product
- product_id
- category
- attributes
- created_at
- updated_at
- active/deleted state if needed

## order
- order_id
- customer_id
- order_status
- purchase_at
- approved_at
- delivered_carrier_at
- delivered_customer_at
- estimated_delivery_at
- created_at
- updated_at

## order_item
- order_id
- item_sequence
- product_id
- seller_id
- quantity where the simulator requires it
- unit_price
- freight_value
- created_at
- updated_at

## payment
- payment_id or deterministic source key
- order_id
- payment_type
- installment_count
- payment_amount
- created_at
- updated_at

### Operational invariants
- source keys are stable;
- money uses decimal;
- timestamps follow one explicit timezone policy;
- foreign keys are enforced where source realism benefits;
- analytics never depend on internal row order.

---

# 13. Incremental extraction strategy

## 13.1 MVP mechanism
Application-level incremental extraction using a source watermark.

Preferred logical cursor:

`(updated_at, stable_primary_key)`

Reason:
timestamp-only cursors can miss or duplicate rows when multiple updates share the same timestamp.

## 13.2 Checkpoint

For each source entity store:

- source/table;
- last successful `updated_at`;
- tie-breaker key;
- last run ID;
- checkpoint committed timestamp.

## 13.3 Atomicity rule

A checkpoint may advance **only after**:

1. source rows are extracted;
2. validation is completed;
3. raw output is durably persisted;
4. run metadata records success for the ingestion stage.

If the process fails before that point, rerunning the old cursor is safe.

## 13.4 Replay overlap

A configurable overlap window may be introduced to capture late updates.

Deduplication must make overlap safe.

---

# 14. Delete strategy

MVP default:
- prefer soft-delete/status fields in the source simulator;
- preserve deleted/inactive state analytically.

Hard-delete propagation via database logs belongs to the CDC phase.

The SDD explicitly avoids pretending timestamp polling perfectly captures hard deletes.

---

# 15. Bronze design

## Purpose
Create replayable source evidence.

## Properties
- append-only;
- source-faithful;
- schema version recorded;
- ingestion timestamp;
- run ID;
- source/entity name;
- extraction cursor/window;
- partitioned by a low-cardinality useful field such as ingestion date/entity.

## Suggested layout

```text
data/bronze/
  orders/
    ingest_date=YYYY-MM-DD/
      part-....parquet
  payments/
  order_items/
  customers/
  products/
  sellers/
```

Exact naming is implementation detail.

## Bronze invariant
A record accepted into Bronze is never silently rewritten merely because downstream logic changes.

---

# 16. Quarantine design

Records failing ingest-level validation must not disappear.

Store:

- original payload/record;
- source entity;
- run ID;
- ingestion timestamp;
- error code;
- error description;
- contract/schema version;
- whether retry/reprocessing is possible.

Examples:

- invalid timestamp;
- malformed identifier;
- impossible numeric type;
- missing required key.

Business inconsistencies that require cross-table context may instead be detected in Silver quality processing.

---

# 17. Silver design

Silver represents cleaned, typed and reusable analytical entities.

Candidate models:

- `stg_customers`
- `stg_sellers`
- `stg_products`
- `stg_orders`
- `stg_order_items`
- `stg_payments`

Silver responsibilities:

- standardize names;
- enforce types;
- normalize timestamps;
- normalize status values;
- deduplicate;
- expose source keys consistently;
- surface data-quality status;
- maintain reusable entity-level logic.

Silver must not contain dashboard-specific metric logic unless that logic is truly an entity invariant.

---

# 18. Gold dimensional model

## 18.1 Grain must be explicit

### `dim_customer`
One row represents one analytical customer entity in its chosen current-state representation.

### `dim_product`
One row represents one product.

### `dim_seller`
One row represents one seller.

### `dim_date`
One row represents one calendar date.

### `fct_orders`
One row represents one order.

### `fct_order_items`
One row represents one order line/item sequence.

### `fct_payments`
One row represents one payment transaction/record according to the source key.

Do not merge facts with different grain simply to reduce table count.

## 18.2 Candidate marts

### `mart_daily_sales`
Grain: one row per calendar date.

Possible metrics:
- orders;
- delivered orders;
- canceled orders;
- units/items;
- gross merchandise value;
- freight;
- average order value.

### `mart_product_performance`
Grain: product + reporting period.

### `mart_seller_performance`
Grain: seller + reporting period.

### `mart_shipping_performance`
Grain: region and/or reporting period.

Possible metrics:
- average delivery days;
- late delivery count;
- late delivery rate.

---

# 19. Canonical metric definitions

Metric definitions must live in version-controlled documentation and ideally dbt metadata/semantic definitions later.

## Order count
Count of distinct `order_id` satisfying the documented status scope.

## Delivered order
An order whose status and/or delivery timestamp meets the canonical fulfillment rule.

## GMV / gross sales
Sum of item value under an explicitly stated cancellation/refund treatment.

## Average order value
`eligible_order_revenue / eligible_order_count`

Never average row-level item values and call it AOV.

## Delivery duration
`delivered_customer_at - purchase_at` or another explicitly selected business definition.

## Late delivery
Delivered date greater than estimated delivery date under the defined timezone/date handling.

Definitions must specify:
- statuses included/excluded;
- refund/cancellation behavior;
- currency assumptions;
- time grain.

---

# 20. Data contracts

Contracts should be machine-readable when implemented.

Initial required contract categories:

## Ingestion contract
For each source entity:
- schema;
- key;
- logical types;
- required fields;
- accepted nullable fields;
- source version;
- freshness/cadence expectation.

## Gold product contract
For each consumer-facing mart:
- grain;
- owner;
- schema;
- metric definitions;
- quality expectations;
- freshness;
- known limitations.

Contracts should be structured to allow later adoption of ODCS-compatible tooling without requiring it in the first working slice.

---

# 21. Data quality

## Ingestion-level
- required keys parse;
- timestamps valid;
- numeric fields parse;
- required columns exist.

## Silver
- order IDs unique where expected;
- order items unique by `(order_id, item_sequence)`;
- payment key unique;
- foreign-key relationships meet documented thresholds;
- statuses belong to accepted domain.

## Business
Examples:
- payment amount must not be negative unless refunds are explicitly modeled;
- purchase time must not occur after delivery;
- item price cannot be negative;
- delivered order should have delivery timestamp;
- delivered timestamp should not predate purchase;
- order item must reference existing order/product/seller.

## Operational
- freshness;
- expected non-zero row volumes on active days;
- sudden row-count changes flagged;
- rejected-row count tracked.

---

# 22. Idempotency guarantees

The system must satisfy:

## Ingestion
Rerunning the same cursor/window does not create duplicate Bronze logical records beyond the intentionally immutable batch evidence.

## Warehouse
Repeated loading produces one canonical representation according to the target key semantics.

## dbt
Rebuilding a model over unchanged inputs produces the same logical output.

## Backfill
Backfilling a historical window and rerunning the normal schedule must converge to the same canonical state.

---

# 23. Orchestration design

Airflow is introduced only after individual pipeline stages work independently.

Conceptual DAG:

```text
extract_entities
      |
validate_ingestion
      |
persist_bronze
      |
load_warehouse_stage
      |
run_dbt_silver
      |
run_silver_tests
      |
run_dbt_gold
      |
run_gold_tests
      |
publish_run_status
```

Parallelize independent extraction tasks only when safe.

A downstream certified layer must not run after an upstream hard failure.

---

# 24. Failure model

## External/source connection failure
- timeout;
- retry limited times;
- exponential backoff;
- do not advance checkpoint.

## Invalid individual record
- quarantine;
- continue batch if contract/business policy permits;
- record rejection count.

## Schema-breaking change
- fail closed for affected entity;
- record contract violation;
- do not silently cast away information.

## dbt test failure
- Gold publication considered failed if a required quality test fails.

## Warehouse unavailable
- preserve Bronze;
- retry loading later;
- no source checkpoint corruption.

## Process interruption
- run must be re-runnable.

---

# 25. Backfill and reprocessing

The system must support a bounded historical run.

Inputs:
- entity/entities;
- start window;
- end window;
- reason/ticket or run note.

Rules:
- backfill may not overwrite raw evidence destructively;
- target state must remain idempotent;
- checkpoints for normal incremental processing must not be accidentally moved backward/forward by ad-hoc backfill;
- backfill runs have distinct run IDs.

---

# 26. Schema evolution

Classify changes:

## Compatible
Example:
- new nullable source field.

## Potentially breaking
- type narrowing;
- renamed column;
- required field added;
- semantic meaning changed.

## Breaking
- key semantics changed;
- field removed while consumed;
- unit/currency meaning changed.

Changes must be:
- versioned;
- tested;
- documented;
- reflected in contracts and downstream models.

No downstream consumer should learn about a breaking schema change only from a runtime exception.

---

# 27. Observability

Every ingestion run should record at minimum:

- `run_id`;
- start;
- end;
- code/repository version when available;
- source entity;
- cursor start/end;
- rows extracted;
- rows accepted;
- rows rejected;
- Bronze files written;
- warehouse rows affected;
- test status;
- retries;
- error category;
- final status.

## Desired future compatibility
The metadata model should make later integration with OpenLineage straightforward:
- Job;
- Run;
- Dataset;
- Inputs;
- Outputs.

Full OpenLineage infrastructure is not required for the MVP.

---

# 28. Logging

Use structured logs.

Required properties:
- timestamp;
- level;
- run ID;
- component/task;
- entity;
- event;
- safe metadata.

Prohibited:
- passwords;
- tokens;
- unnecessary PII;
- raw secret-bearing payloads.

Do not use logs as the only state/checkpoint store.

---

# 29. Security and privacy

Even though the project is local:

- credentials stay outside Git;
- database users should be logically scoped;
- source credentials and warehouse credentials are separate where practical;
- analytical models minimize unnecessary PII;
- public dataset identifiers are not treated as authorization credentials;
- future agent access will not default to unrestricted SQL.

A security document can describe enterprise extensions without implementing expensive infrastructure.

---

# 30. Testing strategy

## Unit tests
Test deterministic Python logic:
- cursor calculation;
- transformations that are not dbt/SQL;
- validation utilities;
- retry classification;
- checkpoint logic.

## Integration tests
Test:
- source PostgreSQL -> ingestion;
- ingestion -> Bronze;
- warehouse load;
- dbt against test database.

## Data tests
- schema;
- uniqueness;
- not-null;
- relationships;
- accepted values;
- business assertions.

## Idempotency test
Run the same logical ingestion twice and confirm target facts are unchanged.

## Failure/recovery test
Force failure before checkpoint commit, rerun, and prove no data is lost.

## Contract test
Introduce a breaking source payload/schema and verify controlled failure/quarantine behavior.

---

# 31. Reproducibility

Target developer workflow eventually:

- clone repository;
- create environment;
- start local dependencies;
- bootstrap deterministic sample data;
- run pipeline;
- run tests;
- inspect Gold outputs.

No cloud account should be necessary for the base demo.

---

# 32. Tool choices and rationale

## Python
Needed for source simulation/ingestion and engineering logic.

## SQL
Primary data manipulation/query language.

## PostgreSQL
Represents realistic OLTP and provides a free local relational target.

## Parquet
Efficient immutable analytical/raw storage.

## dbt
Versioned SQL transformations, testing, documentation and lineage-oriented modeling.

## Airflow
Demonstrates dependency orchestration/backfills and aligns with common DE environments.

Airflow is not required to prove the first extraction function works; it is introduced after the tasks exist.

## Docker / Compose
Reproducible local services.

## pytest
Code-level deterministic testing.

## uv
Python dependency/environment management is acceptable if selected for the repository; dependencies must be pinned and reproducible.

---

# 33. Explicit rejected alternatives for MVP

## Kafka
Rejected because no low-latency durable multi-consumer event requirement exists yet.

## Spark
Rejected because project volume can be handled on a single machine.

## Kubernetes
Rejected because it solves deployment/cluster problems the MVP does not have.

## Data lakehouse
Rejected as primary architecture because structured e-commerce analytics do not require lakehouse transactional semantics at MVP scale.

## Multiple orchestrators
Rejected to avoid control-plane duplication.

## Autonomous agent analytics
Rejected until canonical models, metrics and access controls exist.

---

# 34. Evolution roadmap

## Phase 0 — Design
- Architecture Bible
- SDD
- AGENTS.md
- ADR templates
- data contract drafts
- metric glossary

## Phase 1 — Vertical slice
- operational PostgreSQL
- small source subset
- one incremental entity
- Bronze
- one Silver model
- one Gold mart
- tests
- reproducible run

Goal: prove architecture end-to-end before breadth.

## Phase 2 — Full local batch platform
- all core source entities
- robust incremental extraction
- quarantine
- dbt Silver/Gold
- Airflow
- run metadata
- data-quality suite

## Phase 3 — CI/engineering maturity
- CI checks
- contract validation
- automated integration tests
- documentation generation
- optional lineage integration

## Phase 4 — GCP migration
Possible mapping:
- Bronze -> Cloud Storage
- warehouse -> BigQuery
- orchestration -> retain Airflow/Composer or evaluate managed alternative
- IaC -> Terraform
- transformations -> dbt or Dataform according to portfolio/job target

Architecture must be re-evaluated rather than mechanically cloud-translated.

## Phase 5 — CDC
- PostgreSQL log-based CDC;
- Debezium;
- durable event log;
- delete/update semantics;
- replay.

Kafka is justified here only if the architecture requires the durable event platform.

## Phase 6 — Distributed processing
Introduce Spark only with a workload designed to demonstrate distributed computation and performance reasoning.

## Phase 7 — Agent-ready analytics
- canonical semantic layer;
- business glossary;
- certified agent views/resources;
- read-only tools first;
- MCP if useful;
- authorization;
- evals;
- tool telemetry.

---

# 35. Agent-readiness design

The initial platform should create artifacts that future agents can use safely:

- SDD;
- data contracts;
- metric dictionary;
- dbt documentation;
- lineage;
- freshness metadata;
- run history.

Future AI agent default access:

```text
Gold / certified views
        |
Semantic/context layer
        |
Read-only tools/resources
        |
Agent
```

Do not expose Bronze/raw operational tables directly as the primary business interface.

---

# 36. Acceptance criteria for the first portfolio-complete release

The project is CV-ready only when all are true:

1. A clean environment can reproduce the system from documentation.
2. Historical source data can be bootstrapped.
3. New/changed records can be incrementally ingested.
4. Running the same load twice does not duplicate analytical facts.
5. Raw accepted data is preserved.
6. Invalid records are visible and isolated.
7. Silver models have explicit grain and quality rules.
8. Gold contains at least three useful analytical outputs/marts.
9. Canonical metrics are documented.
10. Required dbt/data tests pass.
11. At least one controlled failure/recovery scenario is demonstrated.
12. Run metadata identifies what each execution processed.
13. No secrets are committed.
14. Architecture diagram and trade-offs are documented.
15. Rejected technologies are explained.
16. The project can be explained without saying "I used X because modern stacks use X."

---

# 37. Interview evidence to capture

The repository should eventually contain evidence/screenshots or reproducible commands showing:

- successful incremental run;
- idempotent rerun;
- failed quality check;
- quarantined bad record;
- Airflow dependency graph;
- dbt lineage/docs;
- Gold query result;
- failure recovery;
- test suite;
- architecture diagram.

The strongest interview narrative is the behavior of the system, not the logo collection.

---

# 38. Initial ADR backlog

Create ADRs before implementation for:

- ADR-001: local-first architecture
- ADR-002: batch before streaming
- ADR-003: PostgreSQL operational source
- ADR-004: immutable Bronze using Parquet
- ADR-005: dbt for analytical transformations
- ADR-006: Airflow as orchestrator after vertical slice
- ADR-007: incremental cursor/checkpoint semantics
- ADR-008: quarantine strategy
- ADR-009: Gold dimensional model
- ADR-010: cloud migration deferred
- ADR-011: agent access deferred until semantic/certified layer

---

# 39. Open questions to resolve before coding

These do not block architecture understanding but should be finalized before implementation details:

1. Exact Olist entities included in the MVP vertical slice.
2. Whether analytical PostgreSQL runs as a second database in one server or separate container.
3. Exact quarantine storage format/location.
4. Exact checkpoint persistence location.
5. Whether the first Gold mart is daily sales or delivery performance.
6. Whether dbt contracts are sufficient initially or an ODCS-compatible contract file is introduced immediately.
7. Exact local dashboard choice, if a dashboard is included at all.
8. Exact CI provider after local MVP.

No new technology should be introduced solely to answer these questions.
