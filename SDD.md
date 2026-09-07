# Software Design Document (SDD)
## Local-First E-commerce Data Platform

**Document version:** 0.2  
**Design status:** Accepted  
**Implementation authorization:** Phase 1 authorized  
**Project stage:** Phase 1 closed; Phase 2 design not started
**Supersedes:** `docs/archive/SDD_v1.md`  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Cost objective:** Zero paid infrastructure for the local portfolio release  

---

# 1. Executive summary

This project builds a local-first data platform for an e-commerce analytics use case. It uses the public Olist Brazilian E-Commerce dataset as historical source evidence and a deterministic operational simulator for subsequent changes.

The platform will:

- bootstrap historical data into an operational PostgreSQL source;
- extract inserts and updates incrementally;
- validate source contracts;
- preserve accepted raw evidence in Parquet;
- preserve rejected records in quarantine;
- load a separate analytical PostgreSQL warehouse;
- build reusable Silver models and certified Gold marts with dbt;
- expose business dates in the Chilean reporting timezone;
- expose monetary metrics in Chilean pesos when monetary entities are introduced;
- support replay, idempotent reruns, controlled failure, and traceable run metadata.

The first implementation is intentionally narrow. Phase 1 proves one complete order-fulfillment path before adding sales, payments, products, orchestration, cloud services, or agent access.

```text
Olist orders CSV
      |
      v
Operational PostgreSQL
      |
      | bounded incremental extraction
      v
Python validation and ingestion
      |
      v
Committed batch envelope
      |
      +------ accepted ------> Bronze Parquet ------> Analytical PostgreSQL
      |                                                   |
      |                                                   v
      |                                          dbt Silver and Gold
      |                                                   |
      |                                                   v
      |                                  mart_daily_order_fulfillment
      |
      +------ rejected ------> Quarantine Parquet   (inspection/correction only)
```

---

# 2. Portfolio narrative

The project should be explainable in an interview as:

> I built a small production-shaped e-commerce data platform using a real public dataset and deterministic simulated changes. It incrementally extracts operational records with a composite cursor, preserves immutable raw evidence, isolates invalid data, recovers from interruption without losing records or duplicating canonical facts, and publishes tested analytical outputs with explicit business semantics.

The strongest evidence is system behavior, not the number of technologies used.

---

# 3. Business problem

Operational systems are optimized for transactions, not analytical scans. Direct analytical access to the source creates performance risk, coupling, weak reproducibility, and inconsistent business definitions.

The platform establishes a controlled analytical boundary for questions such as:

- How many orders were purchased each day?
- How many purchased orders were ultimately delivered or canceled?
- How frequently were delivered orders late?
- How long did delivery take?
- Which source records have fulfillment-quality issues?
- In later phases, how much GMV was generated in BRL and reported in CLP?

The Phase 1 consumer is an analyst or reviewer evaluating order-fulfillment performance. The first mart represents purchase-date cohorts, not a complete order-status event history.

Incorrect published data has a higher cost than one delayed local run. During a failed candidate build, consumers should retain the last certified Gold output rather than receive untested replacement data. This requirement justifies the candidate-to-certified publication boundary used in Phase 1.

---

# 4. Jobs to be done

## JTBD-1 - Incremental ingestion

Ingest new and modified operational orders without repeatedly extracting the entire source.

## JTBD-2 - Safe retry and replay

Retry an interrupted extraction or replay a committed raw batch without duplicating canonical analytical records.

## JTBD-3 - Quality isolation

Prevent structurally invalid rows from silently entering accepted raw data and prevent known business inconsistencies from being silently treated as valid fulfillment outcomes.

## JTBD-4 - Stable business semantics

Calculate fulfillment metrics from one documented definition, reporting dates in `America/Santiago`.

## JTBD-5 - Traceability

Identify what each run processed, its cursor boundaries, files, row counts, tests, publication result, and failure category.

## JTBD-6 - Local reproducibility

Allow another engineer to execute the representative pipeline and tests without paid cloud infrastructure.

---

# 5. Goals

1. Build a complete local batch data pipeline for a realistic e-commerce workload.
2. Keep operational and analytical workloads isolated.
3. Implement deterministic incremental extraction with explicit boundaries.
4. Make retries and replay idempotent at each system boundary.
5. Preserve accepted source evidence in immutable committed Bronze batches.
6. Preserve rejected records and their reasons.
7. Build typed, reusable Silver data and a certified Gold mart.
8. Define business metrics, grain, time, and currency semantics explicitly.
9. Record structured operational metadata from the first vertical slice.
10. Demonstrate failure recovery and contract enforcement with automated tests.
11. Keep the architecture understandable and runnable on a developer laptop.
12. Avoid deliberate local-only coupling when avoiding it does not complicate the MVP.

---

# 6. Non-goals

The local portfolio MVP will not implement:

- real-time streaming;
- CDC or hard-delete capture;
- Kafka, Spark, Flink, or Kubernetes;
- a lakehouse table format;
- microservices;
- cloud deployment or Terraform;
- SCD Type 2 unless a later consumer requires it;
- a full data catalog or semantic-layer product;
- autonomous agents or unrestricted natural-language SQL;
- machine learning;
- foreign-exchange forecasting;
- reconstruction of historical order-status transitions absent from Olist;
- production-grade high availability or disaster recovery.

Airflow is excluded from Phase 1 and introduced only after independently executable stages exist.

---

# 7. Constraints and assumptions

## 7.1 Constraints

- The base release must require no paid infrastructure.
- Runtime dependencies must be pinned and reproducible.
- Secrets and Kaggle credentials must remain outside Git.
- Source and warehouse credentials must be separate.
- The system must run at representative scale on a developer laptop.
- Durable analytical models must use explicit column lists.
- Money must never use binary floating-point semantics.
- Timestamp handling must use named IANA timezones.
- No implementation begins until this SDD and required Phase 0 artifacts are accepted.

## 7.2 Dataset assumptions

- The Olist timestamps are timezone-naive.
- Historical Olist business timestamps are interpreted as `America/Sao_Paulo` for this project.
- The timezone interpretation is an explicit project assumption, not a claim made by the source files.
- Olist monetary values represent Brazilian real even though the files do not include a currency column.
- Olist represents historical final/current states, not complete status-transition event history.
- The operational PostgreSQL schema is simulator-owned and may add clearly identified operational metadata.

### Ambiguous and nonexistent local times

Historical daylight-saving transitions make some naive Sao Paulo timestamps ambiguous or nonexistent.

- For an ambiguous local timestamp, Phase 1 deterministically selects IANA `fold=0`, the earlier occurrence, and records a timezone-resolution quality flag.
- For a nonexistent local timestamp, the row fails timestamp localization and follows the applicable row-quarantine policy.
- The original timestamp text is always preserved.
- Duration and date tests include both ambiguous and nonexistent local-time cases.

The one-hour uncertainty for ambiguous historical records is a documented source limitation. This policy favors deterministic reproducibility over an unsupported claim about the original instant.

## 7.3 Phase 1 concurrency assumption

The deterministic source simulator and incremental extraction do not write the same entity concurrently in Phase 1. A simulator transaction completes before extraction begins. Concurrent source writes require a later update to the incremental-processing ADR.

## 7.4 Representative scale

Phase 1 uses the complete orders file of approximately 99,441 rows plus small deterministic mutation batches. This volume is intentionally suitable for PostgreSQL, Python batch extraction, Parquet, and dbt on one machine.

The performance reference environment allocates at least 4 logical CPU cores, 8 GB RAM, and 10 GB free SSD storage to the local project services. The README records the actual environment used for acceptance evidence.

## 7.5 Local service objectives

- Cadence: manually triggerable and suitable for one scheduled daily run.
- Freshness target: publish Gold within 15 minutes after a healthy Phase 1 run starts on the documented representative local environment.
- Availability objective: no production availability SLO; during a failed candidate build, the last certified Gold output remains queryable while local services are running.
- Process-failure RPO: zero loss of committed Bronze batches.
- Process-failure RTO: operator-triggered recovery within 30 minutes for the tested failure scenarios, excluding total local-disk loss and source re-download time.
- Canonical duplicate tolerance: zero.
- Row-rejection tolerance: the threshold defined in Section 16.

These are portfolio test targets, not claims of production service-level guarantees.

---

# 8. Stakeholders and consumers

## Developer/operator

Needs deterministic commands, explicit state, failure diagnosis, and safe reruns.

## Analyst/reviewer

Needs documented grain, tested metrics, lineage, and known limitations.

## Recruiter/interviewer

Needs a short reproducible path that demonstrates engineering behavior rather than infrastructure breadth.

## Future BI or agent consumer

May consume certified Gold resources later. Bronze and operational tables are not the default consumer interface.

---

# 9. Source dataset

## 9.1 Canonical source

- Name: Brazilian E-Commerce Public Dataset by Olist
- Kaggle identifier: `olistbr/brazilian-ecommerce`
- Canonical URL: `https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce`
- License reported by Kaggle: CC BY-NC-SA 4.0
- Historical period: primarily 2016 through 2018
- Data classification: public, anonymized commercial dataset

The repository must provide attribution and must not claim ownership of Olist data.

## 9.2 Local inventory

The reviewed local directory contains the nine expected files:

| File | Logical rows | Phase |
|---|---:|---|
| `olist_orders_dataset.csv` | 99,441 | Phase 1 |
| `olist_customers_dataset.csv` | 99,441 | Phase 2+ |
| `olist_order_items_dataset.csv` | 112,650 | Phase 2 |
| `olist_order_payments_dataset.csv` | 103,886 | Phase 2+ |
| `olist_order_reviews_dataset.csv` | 99,224 | Deferred |
| `olist_products_dataset.csv` | 32,951 | Phase 2+ |
| `olist_sellers_dataset.csv` | 3,095 | Phase 2+ |
| `olist_geolocation_dataset.csv` | 1,000,163 | Deferred |
| `product_category_name_translation.csv` | 71 | Phase 2+ |

The dataset manifest must record retrieval date when known, or explicitly mark it unavailable without inventing one. It also records verification date, byte size, logical row count, and SHA-256 for every input file.

## 9.3 CSV ingestion requirements

- Parse CSV according to quoting rules; do not use physical newline counts as record counts.
- Read text as UTF-8.
- Handle the UTF-8 BOM in the category translation file.
- Preserve postal prefixes as strings, including leading zeros.
- Preserve original column names in bootstrap-file evidence and manifest documentation, including source misspellings.
- Operational Bronze preserves the explicit operational-source schema, not a false claim that simulator metadata came from the original CSV.
- Preserve multiline review text if reviews are introduced.
- Use explicit source-to-operational mappings.

## 9.4 Known source characteristics

- `customer_id` identifies the order-associated customer row; `customer_unique_id` represents repeat-customer identity.
- The order-item key is `(order_id, order_item_id)`.
- The payment key is `(order_id, payment_sequential)`.
- The observed review key is `(review_id, order_id)`; `review_id` alone is not unique.
- Geolocation postal prefixes are not unique and cannot be joined directly without canonicalization.
- Order items contain no source quantity column. One row represents one item sequence.
- Source monetary columns contain two decimal places but no explicit currency code.

---

# 10. Phase 1 source model

The Phase 1 operational table is `orders`.

## 10.1 Source-derived fields

| Field | Type/semantics | Nullability |
|---|---|---|
| `order_id` | Stable 32-character source identifier | Required |
| `customer_id` | Stable 32-character source identifier | Required |
| `order_status` | Source order status | Required |
| `order_purchase_at` | Localized source business timestamp | Required |
| `order_approved_at` | Localized source business timestamp | Nullable |
| `order_delivered_carrier_at` | Localized source business timestamp | Nullable |
| `order_delivered_customer_at` | Localized source business timestamp | Nullable |
| `order_estimated_delivery_at` | Localized source business timestamp | Required |

For each source-derived business timestamp, the operational table also retains:

- `<field>_source_text` - the exact Olist timestamp text or deterministic synthetic representation;
- `<field>_timezone_resolution` - `exact`, `ambiguous_fold_0`, or `synthetic_aware`.

A nonexistent local timestamp is quarantined during bootstrap and therefore does not enter the operational table. Nullable business timestamps have nullable provenance fields.

## 10.2 Simulator-owned operational fields

| Field | Type/semantics | Nullability |
|---|---|---|
| `source_created_at` | UTC source-system creation instant | Required |
| `source_updated_at` | UTC source-system mutation instant | Required |

These fields do not originate in Olist and must never be presented as historical Olist business timestamps.

The immutable downloaded Olist file plus its manifest is the bootstrap-file evidence. Bronze is evidence of the simulator-owned operational source after the explicit bootstrap mapping. These are different boundaries and use their respective schemas.

## 10.3 Status domain

Phase 1 accepts the eight observed source values:

```text
created
approved
processing
invoiced
shipped
delivered
unavailable
canceled
```

## 10.4 Bootstrap timestamp

The bootstrap command receives or uses a version-controlled `bootstrap_loaded_at`. Every imported order initially receives:

```text
source_created_at = bootstrap_loaded_at
source_updated_at = bootstrap_loaded_at
```

The value must be earlier than all synthetic mutation timestamps. It is deterministic across equivalent clean-environment bootstraps.

## 10.5 Mutation guarantee

Every simulated insert or update sets a non-null UTC `source_updated_at`. For an existing order, the new value must be strictly later than its previous `source_updated_at`.

---

# 11. System boundaries and topology

## 11.1 Operational source

`source-postgres` is a PostgreSQL service containing operational source tables only. Extraction uses a read-only source role after bootstrap/simulation writes finish.

## 11.2 Ingestion application

Typed Python commands perform bounded extraction, contract validation, Parquet persistence, recovery, and warehouse loading. Commands remain independently executable without Airflow.

## 11.3 Bronze and quarantine

Versioned Parquet datasets on a local mounted filesystem preserve accepted and rejected evidence. They are outside both PostgreSQL services.

## 11.4 Analytical warehouse

`warehouse-postgres` is a separate PostgreSQL service with separate credentials and volumes. It contains:

- `control` - checkpoints, runs, attempts, batch manifests, loads, and publications;
- `raw_stage` - loaded committed Bronze records;
- `silver` - typed reusable dbt models;
- `gold_candidate` - immutable versioned candidate relations awaiting tests;
- `gold` - stable certified views.

dbt has no operational-source credentials.

## 11.5 Rationale

Two local PostgreSQL services make the OLTP/OLAP boundary visible and permit independent failure testing. This small cost directly supports source protection and recovery demonstrations.

---

# 12. Phase 1 end-to-end flow

1. Verify the expected Olist orders input against the dataset manifest.
2. Validate the bootstrap CSV structure and parse individual rows.
3. Durably quarantine bootstrap row failures and apply the bootstrap rejection threshold.
4. Bootstrap accepted deterministic order state into `source-postgres`.
5. Read the current orders checkpoint.
6. Recover any previously published extraction batch that has not completed checkpoint registration.
7. Open a stable source snapshot and calculate a fixed extraction upper bound.
8. Extract explicit columns in deterministic pages.
9. Validate operational-source contract rules.
10. Persist accepted and permitted quarantined rows inside one temporary extraction-batch directory.
11. Write checksums and a manifest, then publish that entire directory with one atomic rename on the same filesystem.
12. Register the committed batch and advance the checkpoint in one warehouse control transaction.
13. Load committed, not-yet-loaded Bronze records into `raw_stage` idempotently.
14. Build `silver.stg_orders` with dbt.
15. Build an immutable, versioned Gold candidate relation.
16. Run required dbt and reconciliation tests.
17. Promote the tested candidate through the stable `gold` view.
18. Record final stage and pipeline status.

---

# 13. Incremental extraction semantics

## 13.1 Cursor

The orders cursor is the lexicographically ordered tuple:

```text
(source_updated_at, order_id)
```

`source_updated_at` uses a UTC timestamp with microsecond precision. `order_id` is the deterministic tie-breaker.

## 13.2 Initial extraction

An absent checkpoint means there is no lower bound. The system must not invent a sentinel timestamp or key.

## 13.3 Bounded window

For a non-initial run:

```sql
WHERE (source_updated_at, order_id) > (:cursor_before_timestamp, :cursor_before_order_id)
  AND (source_updated_at, order_id) <= (:cursor_upper_timestamp, :cursor_upper_order_id)
ORDER BY source_updated_at, order_id
```

Rules:

- A preflight check fails the entity if either cursor component is null; such rows cannot be safely ordered or passed by a checkpoint.
- The lower cursor is exclusive.
- The upper cursor is inclusive.
- The upper cursor is the greatest tuple visible in the stable source snapshot at run start.
- Every page uses the same snapshot, upper bound, predicate, and ordering.
- Extraction selects only required columns.
- The source table has an index beginning with `(source_updated_at, order_id)`.
- An empty run records a no-op and does not invent or advance row cursor state.

## 13.4 Cursor after

When every row in a non-empty window is durably accounted for as accepted or permitted quarantine, `cursor_after` equals the fixed `cursor_upper`.

## 13.5 Overlap and late writes

No overlap window is enabled in Phase 1 because simulator writes and extraction are serialized. Concurrent writes, bounded lateness, and overlap semantics require a later ADR update and boundary tests before activation.

## 13.6 Hard deletes

Timestamp polling does not capture hard deletes. The simulator uses statuses or soft-delete fields when deletion semantics are needed. Log-based CDC is outside the MVP.

---

# 14. Recoverable Bronze/checkpoint commit protocol

There is no cross-system transaction spanning the filesystem and PostgreSQL. The system provides deterministic recovery rather than claiming unsupported atomicity.

## 14.1 Identifiers

- `run_id` identifies one pipeline execution.
- `attempt_id` identifies one task attempt.
- `batch_id` deterministically identifies one logical extraction batch.

For Phase 1, `batch_id` is derived from:

```text
source name
entity name
cursor before
cursor upper
ingestion contract version
run mode: incremental or backfill
backfill request ID when run mode is backfill
```

Retries of one backfill reuse its stable request ID. A separately authorized re-extraction of the same range receives a new request ID and therefore a distinct evidence batch. Normal incremental retries retain the same deterministic identity.

## 14.2 Filesystem commit

1. Write accepted Bronze rows and allowed extraction-quarantine rows beneath one temporary batch directory.
2. Close files and calculate size, row count, and SHA-256.
3. Write the batch manifest last.
4. Atomically rename the temporary directory to its deterministic committed path on the same filesystem.
5. Never mutate a committed batch directory.

## 14.3 Control transaction

After publication of a normal incremental batch, one transaction in `warehouse-postgres.control`:

1. verifies that the stored checkpoint still equals `cursor_before`;
2. registers the committed `batch_id` and manifest location;
3. advances the checkpoint to `cursor_after`;
4. records the ingestion stage as successful.

Checkpoint comparison uses a checkpoint version or complete old cursor to prevent concurrent advancement.

After publication of a backfill batch, a separate control transaction registers the committed batch and advances only the backfill request state. It never verifies, advances, or otherwise changes the normal incremental checkpoint.

## 14.4 Recovery

Before starting a new normal source extraction, the command searches for committed incremental manifests whose `cursor_before` matches the current checkpoint but which are not registered as completed in control metadata. Backfill recovery instead uses its stable backfill request ID and never participates in normal-checkpoint recovery.

If one exists:

- verify its deterministic identity and checksums;
- do not re-extract or write another committed batch;
- complete the control transaction;
- continue with downstream loading.

If a temporary directory exists without a valid committed manifest, it is an incomplete attempt and cannot advance the checkpoint.

## 14.5 Single committer

Only one checkpoint-advancing extraction for the same source entity may commit at a time. A compare-and-swap failure is explicit and does not return success.

---

# 15. Bronze design

## 15.1 Purpose

Bronze is immutable source evidence for replay, debugging, and lineage.

## 15.2 Grain

One Bronze row represents one source order version observed in one committed logical extraction batch.

## 15.3 Metadata

Each accepted row or its batch envelope provides:

- source and entity;
- source primary key;
- source mutation timestamp;
- source business timestamps;
- original source timestamp text and timezone-resolution codes;
- `run_id`;
- `batch_id`;
- ingestion timestamp;
- contract version;
- cursor before and upper;
- payload hash;
- source timezone assumption.

## 15.4 Committed extraction-batch layout

```text
data/committed_batches/
  orders/
    cursor_upper_date=YYYY-MM-DD/
      batch_id=<deterministic-id>/
        bronze/
          accepted-*.parquet
        quarantine/
          rejected-*.parquet
        manifest.json
```

`cursor_upper_date` is the UTC date of the logical batch upper cursor, not the wall-clock date of an attempt. It is therefore stable across retries. Bronze and permitted extraction quarantine share one batch root so a single directory rename publishes all accounted-for rows. They remain logically separate datasets within that immutable envelope. The exact file count is controlled to avoid tiny-file proliferation.

## 15.5 Idempotency semantics

- Multiple failed attempts may exist in run metadata.
- A deterministic `batch_id` has at most one committed extraction-batch directory.
- Overlap in a future phase may legitimately re-observe a source version in different logical windows.
- Silver remains responsible for canonical source-version selection.
- Different payload hashes for the same `(order_id, source_updated_at)` are a contract failure.

---

# 16. Quarantine design

## 16.1 Purpose

Quarantine preserves row-level invalid input without contaminating accepted Bronze data or silently losing evidence.

## 16.2 Bootstrap quarantine

Bootstrap-file validation occurs before rows enter operational PostgreSQL. A missing or incompatible required column fails the bootstrap file. Individual malformed CSV records are always preserved under a failed or successful bootstrap attempt and are subject to the rejection threshold before accepted rows are loaded.

```text
data/quarantine/
  bootstrap/
    orders/
      attempt_id=<attempt-id>/
        rejected-*.parquet
```

Bootstrap quarantine has no source checkpoint because incremental extraction has not begun.

## 16.3 Operational extraction quarantine

Operational PostgreSQL enforces database types, but an extracted row can still violate a stricter ingestion contract, such as identifier format, allowed status, or cross-field requirements. Tests may use a dedicated test source schema to simulate an upstream contract violation without weakening normal source constraints.

Permitted extraction-quarantine rows are stored inside the committed batch envelope defined in Section 15.4. This allows accepted and rejected rows to be published by one atomic directory rename.

When extraction exceeds the rejection threshold, its rejected rows are stored under `data/quarantine/extraction/orders/attempt_id=<attempt-id>/`. That failed-attempt evidence is not a committed Bronze batch and cannot advance the checkpoint.

All quarantine records use Parquet with a stable envelope and the original record serialized as text. This permits preservation even when the original record cannot conform to the accepted schema.

## 16.4 Required fields

- `quarantine_id`;
- `run_id` and `attempt_id`;
- candidate `batch_id`;
- source and entity;
- source key when recoverable;
- cursor tuple when recoverable;
- original payload;
- payload hash;
- ordered violation codes;
- safe error descriptions;
- contract version;
- detected timestamp;
- disposition;
- replay or correction reference when available.

`quarantine_id` is deterministic from entity, payload hash, contract version, and violation codes.

## 16.5 Failure policy

Batch-breaking structural changes fail closed and do not advance the checkpoint.

For isolated row failures, a bootstrap or extraction batch may succeed only when both are true:

```text
rejected_count <= 10
rejected_rate <= 1 percent
```

`evaluated_count` is `accepted_count + rejected_count`. `rejected_rate` is `rejected_count / evaluated_count`; it is zero when `evaluated_count` is zero. Any rejection produces a warning.

Exceeding either threshold fails the bootstrap or entity. For extraction it leaves the checkpoint unchanged and prevents publication of an accepted committed batch. All rejected records are still retained durably under the failed attempt; preservation is mandatory, not optional.

## 16.6 Correction

A corrected operational row must receive a later `source_updated_at`. Quarantine history is not destructively rewritten.

---

# 17. Warehouse and Silver design

## 17.1 Raw stage

`raw_stage.orders` loads only registered committed Bronze batches. Loading is idempotent by source record version and batch lineage. Each committed batch is recorded as not loaded, loaded, or failed.

## 17.2 Silver model

`silver.stg_orders` has this grain:

> One row represents the latest deterministic source version of one `order_id`.

Responsibilities:

- select explicit columns;
- standardize field names;
- expose UTC-aware timestamps;
- derive Chilean reporting dates explicitly;
- validate accepted status values;
- select the latest source version deterministically;
- expose quality flags without silently repairing source values;
- retain source and batch lineage.

Current-state selection orders by `source_updated_at` and deterministic lineage fields. Identical source-version tuples with conflicting payloads fail before arbitrary selection.

## 17.3 Known fulfillment-quality flags

Initial flags include:

- delivered status without customer-delivery timestamp;
- customer delivery before purchase;
- customer delivery before carrier handoff;
- carrier handoff before approval;
- other lifecycle inconsistencies explicitly added to the contract.

Status-dependent nulls are not automatically invalid. Their interpretation is defined per status and metric.

---

# 18. Gold model and publication

## 18.1 Gold mart

Model: `mart_daily_order_fulfillment`

Grain:

> One row represents one `reporting_date` derived from order purchase time in `America/Santiago`.

This is a purchase-date cohort mart. Delivered counts describe the latest known outcomes of orders purchased on that date. They do not represent deliveries occurring on that date.

## 18.2 Columns

- `reporting_date`;
- `order_count`;
- `delivered_order_count`;
- `canceled_order_count`;
- `late_delivered_order_count`;
- `late_delivery_eligible_order_count`;
- `late_delivery_rate`;
- `average_delivery_duration_days`;
- `orders_with_fulfillment_quality_issue`;
- publication/run metadata where appropriate.

## 18.3 Candidate and certified states

dbt builds each candidate as a versioned relation such as:

```text
gold_candidate.mart_daily_order_fulfillment__<publication_id>
```

A candidate relation is not overwritten after its build completes. Required contracts, data tests, and reconciliations execute against that exact relation before publication.

After successful tests, one warehouse transaction replaces the stable `gold.mart_daily_order_fulfillment` view so it references the validated candidate and records publication metadata. A failed candidate cannot become visible through the stable view and does not replace the last certified output.

Phase 1 permits only one publication flow at a time. Candidate cleanup never deletes the relation referenced by the stable Gold view. The local retention policy keeps the five most recent successful candidates and failed candidates for seven days.

---

# 19. Canonical Phase 1 metrics

## 19.1 Reporting date

The local calendar date in `America/Santiago` obtained by:

1. interpreting the naive Olist purchase timestamp as `America/Sao_Paulo`;
2. converting it to a UTC instant;
3. converting that instant to `America/Santiago`;
4. taking the Chilean local date.

## 19.2 Order count

Count of distinct structurally accepted `order_id` values for the reporting date across all accepted statuses.

## 19.3 Delivered order count

Count of distinct orders where:

```text
order_status = delivered
and order_delivered_customer_at is not null
and order_delivered_customer_at >= order_purchase_at
```

An order marked delivered without a valid delivery instant remains visible through quality reporting but is not counted as a valid delivered order.

## 19.4 Canceled order count

Count of distinct orders where `order_status = canceled`.

## 19.5 Late delivered order count

Count of valid delivered orders with a non-null estimated delivery instant where:

```text
order_delivered_customer_at > order_estimated_delivery_at
```

Both values are compared as UTC instants after source-timezone interpretation.

## 19.6 Late-delivery eligible order count

Count of valid delivered orders with a non-null estimated delivery instant. This is the denominator for late-delivery rate.

## 19.7 Late-delivery rate

```text
late_delivered_order_count / late_delivery_eligible_order_count
```

The result is null when the denominator is zero. It is not silently replaced with zero.

## 19.8 Average delivery duration

Average elapsed time from purchase instant to customer-delivery instant over valid delivered orders. The output is decimal days and excludes negative or missing durations.

## 19.9 Fulfillment-quality issue count

Count of distinct orders having at least one documented fulfillment-quality flag. Individual issue counts remain available in Silver or quality outputs.

---

# 20. Currency policy

## 20.1 Source currency

Olist monetary values are treated as BRL based on the Brazilian marketplace context. The source files do not carry an explicit currency column, so the assigned `BRL` code is documented enrichment.

## 20.2 Canonical money types

- Python uses `Decimal`, never `float`.
- PostgreSQL source amounts use `NUMERIC(18,2)` for BRL.
- Parquet uses decimal logical type with precision 18 and scale 2 for BRL.
- Values with unexpected fractional precision fail validation rather than being silently rounded.

## 20.3 Chilean reporting currency

When monetary entities enter Phase 2, certified consumer marts expose CLP separately from original BRL amounts.

The conversion contract must preserve:

- original amount and `BRL` currency code;
- converted amount and `CLP` currency code;
- `CLP per BRL` rate;
- rate date;
- authoritative provider;
- provider series identifier;
- retrieval timestamp;
- conversion policy version.

The rate date is based on the purchase date under `America/Sao_Paulo`, unless the Phase 2 metric ADR selects another accounting policy. CLP presentation amounts round to whole pesos using an explicitly tested decimal rounding mode.

No BRL and CLP values may be added in one metric without explicit conversion. Selecting and validating the authoritative historical FX source is a Phase 2 gate and does not block the orders-only Phase 1.

---

# 21. Data contracts

## 21.1 Contract format

Phase 1 uses small repository-owned YAML contracts and dbt model contracts where applicable. ODCS tooling is deferred. No dependency is added solely for future ODCS compatibility.

## 21.2 Required Phase 0 contracts

- `contracts/source/olist_orders.v1.yaml`;
- `contracts/source/operational_orders.v1.yaml`;
- `contracts/gold/mart_daily_order_fulfillment.v1.yaml`.

Bronze manifest, quarantine envelope, and control tables may be specified in the same source contract or a focused control contract if separating them improves clarity.

## 21.3 Minimum contract content

- dataset name and version;
- producer and owner;
- schema and logical types;
- required and optional fields;
- source and business keys;
- field semantics;
- accepted values;
- timezone and currency assumptions;
- quality rules and severity;
- rejection thresholds;
- freshness target;
- compatibility policy;
- PII classification;
- retention;
- failure and quarantine behavior;
- known limitations;
- intended consumers.

## 21.4 Compatibility policy

- Adding an unused nullable field is normally compatible.
- Adding a required field, changing a key, renaming a consumed field, narrowing a type, or changing semantic meaning is breaking.
- Breaking changes fail closed, require a contract version change, and require downstream review.

---

# 22. Data quality policy

## 22.1 Structural hard failures

- missing or renamed required source column;
- incompatible source type;
- any null cursor component: `source_updated_at` or `order_id`;
- conflicting payload for the same source record version;
- manifest checksum or count mismatch.

## 22.2 Row quarantine

- an isolated business timestamp that cannot be parsed or localized;
- an isolated malformed but non-null `order_id`;
- an isolated malformed or null `customer_id`;
- an isolated unsupported status value;
- an isolated row-level type failure that does not indicate schema breakage.

If the same violation affects enough rows to exceed the rejection threshold, the bootstrap or extraction fails. A missing column is a structural failure; an invalid value in an otherwise structurally valid row is a row-level failure.

## 22.3 Silver and business quality

Required tests:

- one canonical row per `order_id`;
- accepted status domain;
- non-null source key and cursor fields;
- deterministic latest-version selection;
- reporting date derivation;
- valid metric denominator behavior;
- Gold reconciliation to eligible Silver orders.

Known source anomalies are preserved and quantified. They are not silently corrected. A rule is marked as blocking, quarantine, or warning in the contract.

## 22.4 Reconciliation

At minimum:

```text
extracted rows = accepted rows + rejected rows
manifest accepted count = readable accepted Parquet count
manifest rejected count = readable quarantine count
registered committed batches = committed manifests
raw-stage source versions = loaded committed accepted versions
Gold order counts = eligible Silver order counts by reporting date
```

## 22.5 Statistical checks

Row-count changes, freshness, and null-rate movement begin as warnings until a meaningful baseline exists. They do not become hard gates without evidence and an accepted contract change.

---

# 23. Idempotency guarantees

## Bootstrap

Running the same bootstrap against equivalent input converges to the same operational state and deterministic operational timestamps.

## Extraction attempt

Retrying an interrupted attempt cannot create a second committed directory for the same `batch_id`.

## Checkpoint

The normal incremental checkpoint advances once for each committed normal incremental batch and only after all extracted rows are durably accounted for. A backfill batch never changes that checkpoint; its separate request state advances according to the committed backfill batch.

## Warehouse load

Loading the same committed Bronze batch repeatedly converges to one canonical representation of each source record version.

## Silver

Unchanged source versions produce the same latest order state.

## Gold

Unchanged Silver input and metric version produce the same logical mart output.

## Backfill and replay

Replaying committed Bronze or repeating a bounded source backfill converges to the same canonical Silver and Gold state.

No component claims exactly-once delivery. The design uses retry-safe, at-least-once processing with idempotent convergence.

---

# 24. Failure, retry, and recovery

## Source unavailable

- use explicit connection and operation timeouts;
- retry only classified transient failures;
- use bounded exponential backoff;
- do not advance checkpoint.

## Invalid individual row

- preserve it in quarantine;
- apply the configured rejection threshold;
- report rejection counts and codes;
- do not silently drop it.

## Breaking schema change

- fail the entity closed;
- preserve failure evidence;
- do not write a committed accepted batch;
- do not advance checkpoint.

## Crash before filesystem publication

- temporary output is not a committed batch;
- checkpoint remains unchanged;
- rerun extraction safely.

## Crash after filesystem publication but before checkpoint commit

- recover the deterministic committed manifest;
- verify checksums;
- complete the control transaction without writing another batch.

## Warehouse unavailable after Bronze commit

- Bronze remains committed;
- checkpoint registration recovery occurs when warehouse returns;
- downstream loading resumes from registered committed batches.

## Warehouse load failure

- source checkpoint is not moved backward;
- failed load remains replayable from committed Bronze;
- rerun the idempotent load.

## dbt test failure

- candidate Gold is not promoted;
- the last certified Gold output remains available;
- publication status is failed.

## Retry policy

Every external operation defines timeout, retryable categories, non-retryable categories, maximum attempts, and backoff. Poison data is never retried indefinitely.

---

# 25. Backfill and replay

## 25.1 Source backfill

A source backfill re-extracts a bounded mutation-cursor range using the same `(start, end]` semantics as normal extraction.

- It has a distinct run ID, stable backfill request ID, and required reason.
- Retries reuse the same backfill request ID; a separately authorized re-extraction uses a new request ID.
- It never updates the normal incremental checkpoint.
- It writes new Bronze evidence only when it performs a genuine source extraction with a distinct logical batch identity.
- It may not commit concurrently with normal extraction for the same entity and overlapping range.

## 25.2 Bronze replay

A Bronze replay selects existing committed `batch_id` values and rebuilds warehouse, Silver, or Gold state without querying the source and without writing another Bronze batch.

## 25.3 Canonical precedence

Canonical state is determined by source-version semantics, not ingestion or replay time.

---

# 26. Observability and logging

## 26.1 Operational entities

The control model distinguishes:

- pipeline run;
- entity ingestion run;
- task attempt;
- committed batch;
- warehouse batch load;
- dbt build/test result;
- Gold publication.

## 26.2 Required metadata

- `run_id`, `attempt_id`, and `batch_id`;
- source and entity;
- start, end, and duration;
- code commit when available;
- contract and metric versions;
- cursor before, upper, and after;
- rows extracted, accepted, rejected, and loaded;
- rejection counts by code;
- manifest and file paths;
- file sizes and checksums;
- retry count;
- test names and results;
- candidate and published Gold versions;
- failure category and safe error message;
- final stage status.

## 26.3 Status model

Statuses include, as applicable:

```text
pending
running
bronze_committed
checkpoint_committed
warehouse_loaded
quality_failed
published
failed_retryable
failed_terminal
no_op
```

A stage is not marked successful before the state it claims is durable.

## 26.4 Structured logs

Logs include timestamp, level, run context, component, entity, event, and safe metadata. Logs never include credentials, tokens, unnecessary PII, or secret-bearing payloads. Logs are not the checkpoint store.

---

# 27. Security, privacy, and licensing

- Kaggle credentials remain outside Git and logs.
- Local configuration is environment-driven and documented.
- Source and warehouse database users are distinct.
- Extraction receives source read privileges only.
- dbt receives warehouse privileges only.
- Public identifiers are treated as data, not credentials.
- Raw data is not the default consumer interface.
- Customer identifiers are excluded from Gold when not needed.
- Dataset attribution and license are documented in the README and manifest.

The full local dataset should not be committed by default. The repository should contain download instructions, checksums, and small deterministic synthetic fixtures for automated tests. Any redistribution must comply with the source license.

---

# 28. Reproducibility and developer workflow

The target Phase 1 workflow is:

```text
clone repository
create pinned environment
start source and warehouse PostgreSQL
verify or obtain source data
bootstrap deterministic orders
run initial pipeline
apply deterministic order mutations
run incremental pipeline
run tests
query certified Gold mart
run failure/recovery demonstration
```

The quick-start path uses documented non-interactive commands. Tests use small deterministic synthetic fixtures so routine verification does not require Kaggle credentials or the full dataset.

No critical setup may depend on undocumented local state.

---

# 29. Testing strategy

## 29.1 Unit tests

- cursor tuple comparison;
- initial and bounded cursor predicates;
- pagination boundaries with equal timestamps;
- deterministic `batch_id` and `quarantine_id`;
- manifest checksums and count validation;
- timezone localization and Chilean date conversion;
- status and row validation;
- metric eligibility and denominator behavior;
- Decimal and future CLP rounding behavior.

## 29.2 Integration tests

- bootstrap to source PostgreSQL;
- source snapshot to Bronze;
- quarantine persistence;
- Bronze to warehouse load;
- dbt build against test warehouse;
- Gold candidate promotion.

## 29.3 Data and dbt tests

- schema and contracts;
- not-null;
- uniqueness;
- accepted values;
- deterministic latest source version;
- lifecycle quality flags;
- mart grain;
- metric reconciliation.

## 29.4 Required idempotency test

Run the same logical batch twice and prove:

- one committed `batch_id`;
- no duplicate canonical source versions;
- unchanged Silver state;
- unchanged Gold results.

## 29.5 Required failure/recovery test

Inject failure after Bronze filesystem publication but before control transaction commit. Rerun and prove:

- no accepted source row is lost;
- no second committed batch is written;
- checkpoint converges to the expected cursor;
- downstream state remains idempotent.

## 29.6 Required contract test

Introduce a breaking orders schema and prove controlled failure without checkpoint advancement.

## 29.7 Required quarantine tests

Introduce malformed bootstrap-file rows and prove their payloads and violations are durable and that bootstrap threshold policy is enforced. Separately simulate a stricter operational-contract violation in a dedicated test source schema and prove extraction quarantine and checkpoint behavior.

## 29.8 Required publication test

Force a required Gold test to fail and prove the previously certified Gold output remains published.

---

# 30. Orchestration

Airflow is not part of Phase 1. Each pipeline stage must first exist as an independently executable and tested command.

When Phase 2 has multiple stable dependent stages, one Airflow DAG may orchestrate:

```text
extract and commit entities
        |
load committed Bronze
        |
build Silver candidates
        |
run Silver tests
        |
build Gold candidates
        |
run Gold tests
        |
publish certified Gold
```

Airflow does not contain transformation logic or serve as the only checkpoint store.

---

# 31. Architecture decisions and governance

Phase 0 requires these accepted ADRs:

1. Local topology and source/warehouse separation.
2. Incremental cursor, Bronze commit, checkpoint, and recovery protocol.
3. Contract, quality severity, and quarantine policy.
4. Fulfillment mart grain, metrics, and certified publication.

Batch processing, rejected distributed technologies, and future agent access remain documented in this SDD unless a material change requires another ADR.

An ADR explains and refines a decision. It does not silently override contradictory SDD text. A material architecture change requires both an ADR and a synchronized SDD revision. Until both are accepted, the current accepted SDD remains authoritative.

## 31.1 SDD promotion record

`AGENTS.md` names `SDD.md` as the project source of truth. This document was promoted through the following procedure:

1. record user approval of this document and the required Phase 0 artifacts;
2. archive the original `SDD.md` as `docs/archive/SDD_v1.md`;
3. promote the reviewed V2 contents to the canonical path `SDD.md`;
4. set its status, approver, and acceptance date;
5. change the four ADRs, three contracts, metric glossary, and test matrix from `Proposed` to `Accepted` with the same approval date;
6. update the README status and documentation map;
7. verify that ADRs and contracts reference canonical `SDD.md`.

The procedure completed on 2026-09-06. This canonical `SDD.md` is authoritative and the original design is retained at `docs/archive/SDD_v1.md` for historical reference.

---

# 32. Risks and limitations

| Risk or limitation | Consequence | Mitigation |
|---|---|---|
| Olist timestamps have no authoritative timezone | Dates and durations may differ from original business interpretation | Document Sao Paulo assumption, preserve raw text, use IANA rules |
| Brazil source and Chile reporting can cross date boundaries | Daily cohort counts differ by reporting timezone | Define conversion and date role in metric contract |
| Filesystem and PostgreSQL cannot commit atomically together | Orphan committed file or stale checkpoint | Deterministic manifest-first recovery and compare-and-swap checkpoint |
| Timestamp polling cannot capture hard deletes | Deleted source state can be missed | Soft-delete/status in MVP; CDC deferred |
| Phase 1 serializes writes and extraction | General concurrent polling correctness is not demonstrated | State limitation; redesign and test before concurrency |
| Olist is final/current-state history | Missing intermediate order transitions | Do not claim event history; synthetic transitions begin after bootstrap |
| Known lifecycle inconsistencies exist | Naive hard tests would reject real historical data | Preserve, flag, quantify, and exclude only where metric eligibility requires |
| Full dataset is externally hosted | Clean run may require source access and Kaggle terms | Manifest, download instructions, checksums, synthetic test fixtures |
| Local disk loss can remove Bronze and control state | Infrastructure-level data loss | Reproducible bootstrap; production disaster recovery is outside MVP |
| Future FX source is not yet selected | CLP monetary marts cannot be certified | Make authoritative FX selection a Phase 2 gate |
| Scope expansion delays working evidence | Portfolio remains documentation-only | Enforce vertical-slice phase gates |

Portfolio reliability targets for representative Phase 1 runs are:

- zero accepted-record loss in tested process-failure scenarios;
- zero duplicate canonical order facts after retry or replay;
- recoverability from committed Bronze without querying source again;
- deterministic results from equivalent input and configuration.

These targets are tested properties, not claims of production high availability.

---

# 33. Roadmap

## Phase 0 - Accepted design

- accepted canonical `SDD.md` promoted through Section 31.1;
- recruiter-facing README skeleton;
- four accepted ADRs;
- bootstrap and operational orders contracts;
- Gold mart contract;
- metric glossary;
- dataset manifest with checksums;
- Phase 1 test matrix.

## Phase 1 - Orders fulfillment vertical slice

- two PostgreSQL services;
- deterministic Olist orders bootstrap;
- deterministic order mutation scenarios;
- bounded incremental extraction;
- Bronze and quarantine Parquet;
- control metadata and checkpoint recovery;
- warehouse raw stage;
- `stg_orders`;
- `mart_daily_order_fulfillment`;
- candidate-to-certified publication;
- unit, integration, dbt, idempotency, and failure-recovery tests;
- reproducible commands and evidence.

## Phase 2 - Local commerce expansion

- customers, order items, payments, products, and sellers;
- source-currency BRL metrics;
- authoritative historical FX dataset and CLP reporting;
- GMV and AOV definitions;
- additional Silver models and Gold marts;
- broader quarantine and reconciliation;
- Airflow after tasks work independently.

## Phase 3 - Engineering maturity

- CI provider selection;
- automated contract validation;
- generated dbt documentation;
- optional lineage integration;
- optional local dashboard if it strengthens evidence.

## Later phases

Cloud migration, CDC, distributed processing, and agent-facing analytics require new requirements and ADRs. They impose no implementation requirements on Phase 1.

---

# 34. Phase 0 exit criteria

Phase 0 is complete only when:

1. The promotion procedure in Section 31.1 is complete and canonical `SDD.md` has status `Accepted`, an accepted date, and an approver.
2. The four required ADRs are accepted.
3. The bootstrap and operational orders contracts exist and the bootstrap contract matches the reviewed file.
4. The fulfillment mart contract and metric glossary contain the definitions in this SDD.
5. The dataset manifest records expected files, logical counts, sizes, and checksums.
6. Cursor predicates, boundaries, snapshot assumptions, and recovery behavior are reflected consistently across documents.
7. Quarantine thresholds and quality severities are reflected in the contract.
8. The Phase 1 test matrix includes boundary, idempotency, failure, and publication tests.
9. There are no unresolved decisions that block the orders-only vertical slice.
10. The README clearly states current status and does not claim unimplemented behavior.

Phase 0 acceptance authorizes only Phase 1. It does not authorize monetary marts until the Phase 2 FX gate is resolved.

---

# 35. Phase 1 acceptance criteria

Phase 1 is complete only when all are true:

1. A clean documented environment starts source and warehouse services.
2. The reviewed Olist orders file can be bootstrapped deterministically.
3. A deterministic fixture path permits routine tests without Kaggle credentials.
4. Initial extraction processes all order rows through an explicit bounded cursor.
5. At least one synthetic insert and one status update are captured incrementally.
6. Equal-timestamp cursor boundaries are tested without missing or duplicating rows.
7. One logical retry produces one committed Bronze batch.
8. A crash after Bronze publication and before checkpoint commit recovers successfully.
9. Breaking schema input fails closed without checkpoint advancement.
10. Row-level malformed input is preserved in quarantine and threshold behavior is tested.
11. `stg_orders` has one deterministic current row per order.
12. Known Olist fulfillment anomalies remain visible and are not silently corrected.
13. The Gold mart matches its documented grain and metric definitions.
14. A failed required Gold test does not replace the last certified output.
15. Source, Bronze, warehouse, Silver, and Gold counts reconcile under their documented semantics.
16. Structured metadata explains each execution and its cursor movement.
17. Targeted and broader relevant tests pass.
18. No secrets or raw Kaggle credentials are committed.
19. The complete Phase 1 path runs without Airflow.
20. Timing evidence records the reference environment and demonstrates or explains any deviation from the 15-minute healthy-run freshness target.

---

# 36. Interview evidence

The repository should provide reproducible commands or captured output demonstrating:

- architecture and source/warehouse separation;
- deterministic historical bootstrap;
- initial and incremental runs;
- cursor before and after;
- idempotent rerun;
- committed Bronze manifest;
- quarantined malformed row;
- schema-breaking controlled failure;
- crash-before-checkpoint recovery;
- dbt lineage and tests;
- failed-candidate publication protection;
- certified Gold query;
- explicit Brazil-source and Chile-reporting semantics.

Screenshots may supplement executable proof but cannot replace it.

---

# 37. Deferred decisions and gates

These decisions do not block Phase 1:

- authoritative historical BRL-to-CLP rate provider and fallback-day policy;
- Phase 2 GMV cancellation and refund treatment;
- customer-history strategy beyond current state;
- geolocation canonicalization;
- dashboard selection;
- CI provider;
- Airflow scheduling details;
- cloud, CDC, distributed, and agentic architecture.

Each item becomes blocking only before the phase that implements it. Business semantics must be accepted before the corresponding model is written.

---

# 38. Design acceptance

Accepted decision:

```text
SDD version 0.2 is Accepted.
Phase 1 implementation is authorized.
```

Phase 0 artifacts were explicitly approved by Juan Pablo and promoted on 2026-09-06. Material changes now require the governance process in Section 31.
