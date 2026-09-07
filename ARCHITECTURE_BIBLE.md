# Architecture Optimization Bible
## Data Engineering & Agentic Systems — 2026 Edition

**Purpose:** reusable architecture constitution to provide to an AI coding assistant, architecture agent, or human collaborator **before** asking for an SDD, implementation plan, or code.

**Status:** living document  
**Scope:** data engineering, analytics engineering, data platforms, data products, AI/agent data access, portfolio and production-oriented projects  
**Primary goal:** maximize architectural correctness and learning value while minimizing unnecessary complexity, cost, fragility, and tool-driven design.

---

# 0. How to use this document

Before asking an AI agent to design a system:

1. Provide this document as architecture context.
2. Provide the project-specific problem statement and constraints.
3. Ask for an SDD **before code**.
4. Require explicit assumptions, trade-offs, rejected alternatives, failure modes, and acceptance criteria.
5. Do not authorize implementation until the SDD is internally consistent.
6. For material architectural changes, require an ADR (Architecture Decision Record).
7. When the implementation exists, require tests and evidence before accepting "done."

This document is intentionally opinionated. Its defaults are not laws. A project may deviate from them only when a concrete requirement justifies the deviation.

---

# 1. Prime directives

## 1.1 Problem before platform

Architecture must start with:

- the business or user problem;
- jobs to be done;
- producers and consumers;
- correctness requirements;
- latency requirements;
- expected scale;
- operational constraints;
- security/privacy;
- cost limits;
- team capability.

Never select Kafka, Spark, a lakehouse, Kubernetes, GraphQL, MCP, vector databases, or a cloud service solely because the technology is popular.

**Rule:** every significant component must answer:  
**What requirement becomes materially harder or impossible if this component is removed?**

If the answer is weak, remove the component.

---

## 1.2 Prefer the smallest architecture that satisfies the SLOs

Default preference:

1. deterministic local process;
2. single database / analytical engine;
3. scheduled batch;
4. explicit transformations;
5. one orchestrator only if orchestration is actually needed;
6. distributed systems only when demonstrated requirements demand them.

Complexity is a cost paid permanently in:

- debugging;
- deployment;
- upgrades;
- observability;
- security;
- documentation;
- cognitive load;
- agent context;
- money.

**Optimization target:** minimize total system complexity subject to correctness, recoverability, security and required performance.

---

## 1.3 Reliability before scalability

Before optimizing for millions of events per second, establish:

- deterministic identifiers;
- idempotency;
- replay/reprocessing;
- schema validation;
- tests;
- explicit failure states;
- lineage/run metadata;
- observability;
- backup/recovery strategy;
- data ownership.

A fast pipeline that silently produces wrong data is a failed system.

---

## 1.4 Separate operational and analytical concerns

Transactional workloads and analytical workloads optimize for different behaviors.

### OLTP
Prioritize:

- ACID;
- low-latency point reads/writes;
- normalized state;
- referential integrity;
- bounded transactions.

### OLAP
Prioritize:

- scans and aggregations;
- historical analysis;
- dimensional or analytical models;
- columnar formats;
- partition pruning;
- reproducible transformations.

**Default:** do not run heavy analytical queries directly against the operational database.

---

## 1.5 Contracts at boundaries

Every important boundary should define:

- schema;
- field types;
- required fields;
- semantics;
- allowed values/ranges;
- version;
- compatibility expectations;
- freshness expectation;
- ownership;
- failure behavior.

Contracts may exist for:

- APIs;
- files;
- messages/events;
- source tables;
- data products;
- agent tools;
- semantic metrics.

Prefer machine-readable, version-controlled contracts where feasible.

---

## 1.6 Raw data is evidence

When replay, auditability or debugging matter, preserve a raw representation close to the source.

A raw layer should normally be:

- immutable or append-only;
- timestamped;
- attributable to a source;
- recoverable;
- partitioned sensibly;
- protected from accidental consumer access.

Do not mutate raw history merely to make downstream modeling easier.

**Exception:** if the source is trivial, fully reproducible, inexpensive, and already versioned, a separate raw layer may not add enough value.

---

## 1.7 Idempotency is a default requirement

Running the same logical load twice must not silently duplicate business facts.

Design explicitly for:

- stable primary/business keys;
- deterministic checkpoints;
- upsert/merge semantics where appropriate;
- deduplication;
- replay;
- atomic checkpoint advancement.

Never update a checkpoint before the associated data has been durably accepted.

---

## 1.8 Batch is the default; streaming must earn its complexity

Use batch when the business can tolerate minutes/hours/day latency.

Move toward streaming only when required by:

- user-facing real-time behavior;
- operational automation;
- fraud/risk;
- alerting;
- very high ingestion rates;
- event-driven integration;
- strict freshness SLOs.

Do not build a Kafka architecture to refresh a daily dashboard.

---

## 1.9 Business semantics are architecture

Definitions such as:

- revenue;
- active customer;
- fulfilled order;
- churn;
- gross margin;
- late delivery;

must not be duplicated across dashboards, notebooks, SQL scripts and agent prompts.

Create a canonical semantic/metrics layer or at minimum a version-controlled metrics dictionary.

An AI agent cannot reliably infer organization-specific semantics from column names alone.

---

## 1.10 Agents consume trusted context, not uncontrolled raw data

Agentic access changes the risk model because non-deterministic software can act confidently on stale or ambiguous context.

Default agent data path:

`raw/source -> validation -> modeled/certified data -> semantic/context layer -> read-only agent access`

Not:

`agent -> unrestricted production database`

Agent-visible datasets require explicit:

- schema;
- semantics;
- freshness;
- quality;
- access policy;
- lineage;
- owner.

---

# 2. Mandatory intake before architecture

An SDD must not be generated until the following questions have answers or explicit assumptions.

## 2.1 Business

- What problem is being solved?
- Who consumes the result?
- What decision/action does the data enable?
- What is the cost of wrong data?
- What is the cost of late data?
- What is the cost of unavailable data?

## 2.2 Sources

For each source:

- owner;
- interface: database/API/file/webhook/event stream;
- authentication;
- schema stability;
- data volume;
- update rate;
- retention;
- historical access;
- rate limits;
- known quality issues;
- support for incremental extraction;
- support for CDC;
- presence of PII/secrets.

## 2.3 Consumers

- BI/dashboard;
- analysts;
- applications;
- ML;
- reverse ETL;
- APIs;
- AI agents;
- external clients.

For each consumer define:

- schema expectations;
- freshness;
- latency;
- concurrency;
- access level;
- required history.

## 2.4 Scale

Capture current and expected:

- rows/day;
- bytes/day;
- total retained bytes;
- requests/sec;
- peak events/sec;
- number of sources;
- number of models;
- number of consumers;
- concurrency.

Do not use "big data" as a requirement.

## 2.5 Reliability

Define:

- freshness SLO;
- availability SLO;
- RPO;
- RTO;
- maximum acceptable data loss;
- maximum acceptable duplicate rate;
- maximum acceptable invalid record rate.

## 2.6 Constraints

- monthly budget;
- local/cloud/on-prem;
- operating system;
- hardware;
- team size;
- existing stack;
- regulatory/privacy constraints;
- vendor restrictions;
- deployment restrictions;
- learning/portfolio goals.

---

# 3. Decision ladder: ingestion pattern

Choose the lowest-complexity pattern that meets requirements.

## 3.1 Full snapshot

Use when:

- source is small;
- extraction is cheap;
- change history is unnecessary;
- implementation simplicity dominates.

Avoid when repeated scanning stresses the source or volume grows significantly.

## 3.2 Incremental polling

Use when:

- source exposes reliable `updated_at`, sequence IDs, cursors, or pagination tokens;
- minute/hour/day latency is acceptable.

Require:

- deterministic watermark;
- tie-breaker for equal timestamps;
- checkpoint only after durable load;
- replay window when late updates are possible.

Recommended composite cursor pattern:

`(updated_at, primary_key)`

rather than timestamp alone.

## 3.3 Webhook

Use when:

- source can push events;
- rapid notification matters;
- polling would waste requests.

Receiver must be:

- fast;
- idempotent;
- authenticated;
- able to absorb bursts;
- decoupled from slow downstream work.

Acknowledge only after the event has been safely accepted.

## 3.4 CDC

Use when:

- database mutations matter;
- low-latency replication is required;
- source querying must be minimized;
- inserts/updates/deletes must be captured reliably.

Prefer log-based CDC over repeated analytical scans.

CDC requires explicit handling of:

- schema evolution;
- ordering;
- tombstones/deletes;
- replay;
- snapshots/bootstrap;
- exactly-once expectations versus practical at-least-once delivery.

## 3.5 Streaming/event platform

Use when consumers need:

- an ordered durable log;
- replay;
- independent offsets;
- multiple consumers;
- event-time processing.

Do not confuse a durable event log with a transient work queue.

---

# 4. Decision ladder: queue versus event log

## Work/message queue

Prefer when:

- a unit of work should normally be processed once by one worker;
- acknowledgment removes/completes the work;
- historical replay is not a primary requirement.

Examples of conceptual use:
- background job;
- email task;
- image processing task.

## Event streaming platform

Prefer when:

- events form business history;
- multiple consumers need the same events;
- replay matters;
- consumers advance independent offsets;
- ordering per key/partition matters.

Examples:
- order state changes;
- clickstream;
- CDC;
- telemetry.

**Do not choose on brand name; choose on semantics.**

---

# 5. Decision ladder: API/interface style

## REST

Default for:

- resource-oriented public/internal APIs;
- broad compatibility;
- stateless request/response;
- simple integrations.

## gRPC

Consider for:

- service-to-service traffic;
- strict contracts;
- high request volume;
- low latency;
- efficient binary transport;
- controlled clients.

## GraphQL

Consider when:

- clients genuinely need flexible graph-shaped reads;
- many consumer-specific projections would otherwise proliferate endpoints.

Do not introduce GraphQL solely to avoid designing stable domain APIs.

## Webhooks

Use for push notification, not as a replacement for every query interface.

## MCP/tool interfaces

Use for AI/agent access when tools/resources are the consumer interface.

Treat agent tools as contracts for a **non-deterministic client**:
- narrow purpose;
- clear names;
- strict inputs;
- bounded outputs;
- explicit side effects;
- authorization;
- auditable execution.

---

# 6. Storage decision framework

## Relational warehouse/database

Prefer when:

- data is mostly structured;
- SQL is the primary consumption path;
- scale fits a modern relational/warehouse engine;
- governance and simplicity matter.

For small projects, PostgreSQL or DuckDB may be more appropriate than a lake.

## Object storage + Parquet

Prefer when:

- cheap raw/history retention matters;
- replay is valuable;
- datasets are large;
- multiple engines may read the same data;
- columnar scan efficiency matters.

## Lakehouse

Choose only if transactional table semantics over object storage solve a real requirement:
- very large mutable analytical datasets;
- multiple engines;
- schema evolution;
- streaming/batch convergence.

## NoSQL / key-value / document

Use because access patterns require it, not because source payloads are JSON.

---

# 7. File format and serialization defaults

## Parquet

Default for analytical files when:

- column pruning matters;
- compression matters;
- batch analytics dominates.

Design:
- avoid tiny-file explosions;
- choose partitions based on actual query pruning;
- avoid high-cardinality partition keys;
- store appropriate logical types.

## JSON

Good for:
- interoperability;
- raw event envelopes;
- debugging.

Poor as a default analytical storage format at scale.

## CSV

Accept as interchange when required, but validate:
- encoding;
- delimiter;
- quoting;
- malformed rows;
- column drift;
- locale-dependent dates/numbers.

## Arrow

Use for in-memory columnar interoperability when a measurable cross-system data movement problem exists.

Do not force Arrow into an architecture because it is theoretically efficient.

---

# 8. Transformation architecture

## ELT first when warehouse SQL is sufficient

Prefer transformations in the analytical engine when:

- data is already loaded;
- SQL expresses the logic clearly;
- the warehouse can perform the work efficiently.

Benefits:
- less data movement;
- query pushdown;
- lineage;
- easier testing;
- centralized business logic.

## Python

Use for:
- API extraction;
- complex parsing;
- non-SQL transformations;
- external services;
- validation;
- workflow glue.

Avoid pulling millions of rows into Python merely to filter/aggregate data that the database can process.

## Spark

Spark must have a justification such as:

- dataset does not fit practical single-node processing;
- distributed shuffle/compute is required;
- organization already operates Spark;
- portfolio phase explicitly targets distributed processing concepts.

Do not add Spark to a small pipeline to signal seniority.

---

# 9. Data modeling rules

## 9.1 Define grain first

Every analytical table/model must state:

> One row represents ______.

Do not build a fact table before this sentence is unambiguous.

## 9.2 Dimensions and facts

Use dimensional modeling when analytics benefits from:
- stable business entities;
- reusable dimensions;
- consistent metrics;
- understandable joins.

## 9.3 History

Choose deliberately:

- current-state overwrite;
- event history;
- snapshot;
- SCD Type 2;
- append-only state transitions.

Do not preserve every version unless a consumer requires history.

## 9.4 Keys

Separate where useful:

- source/business key;
- warehouse surrogate key;
- deterministic integration key.

Natural keys must be evaluated for stability.

## 9.5 Currency and money

Use fixed-precision decimal, not binary floating point.

Always store:
- amount;
- currency;
- relevant conversion context if conversion exists.

## 9.6 Time

Default:
- store timestamps in UTC;
- preserve source timezone when semantically necessary;
- perform presentation conversion downstream.

Never mix naive and timezone-aware timestamps without explicit rules.

---

# 10. Medallion without dogma

Bronze/Silver/Gold is a communication pattern, not a mandatory number of physical copies.

## Bronze
Purpose:
- ingestion evidence;
- replay;
- source fidelity.

## Silver
Purpose:
- schema enforcement;
- normalization;
- deduplication;
- integration;
- quality gates;
- reusable cleaned data.

## Gold
Purpose:
- certified consumer-facing models;
- business semantics;
- marts/data products.

Skip or merge a layer when it adds no independent value.

**Required question for each layer:**  
What invariant becomes true here that was not true in the previous layer?

If there is no answer, the layer may be unnecessary.

---

# 11. Data contracts

A meaningful data contract should capture more than column names.

Minimum:

- dataset name/version;
- owner;
- schema;
- logical types;
- required/optional fields;
- primary/business key;
- quality rules;
- freshness/SLA;
- compatibility policy;
- PII classification;
- retention;
- consumer expectations.

Prefer version control and CI validation.

Breaking changes should be explicit, not discovered in downstream production failures.

---

# 12. Data quality strategy

Quality is layered.

## L0 — structural
- parse succeeds;
- expected columns exist;
- types are valid.

## L1 — row constraints
- non-null;
- range;
- allowed values;
- regex/format.

## L2 — relational
- uniqueness;
- foreign key/reference validity;
- cardinality expectations.

## L3 — business
- paid order has positive payment;
- shipped timestamp cannot precede purchase;
- refund cannot exceed captured payment without documented reason.

## L4 — statistical/operational
- row count anomalies;
- distribution shift;
- freshness;
- unexpected null-rate changes.

## L5 — cross-system reconciliation
- source count versus warehouse count;
- financial totals;
- control totals.

AI may propose candidate checks or investigate anomalies, but **deterministic checks remain the acceptance gate** unless there is a strong reason otherwise.

---

# 13. Invalid data: quarantine and DLQ

Do not choose between "drop the bad row" and "fail the entire world" without thought.

For row-level invalid data:
- preserve payload;
- attach reason;
- attach source/run ID;
- attach detected timestamp;
- prevent contamination of certified data;
- support inspection and replay.

Use a quarantine table/dataset for batch data.

Use a DLQ for asynchronous message/event failure when appropriate.

Do not use a DLQ as a substitute for fixing systematic producer defects.

---

# 14. Retry and failure policy

Every external call must define:

- connect timeout;
- read/operation timeout;
- retryable errors;
- non-retryable errors;
- maximum attempts;
- exponential backoff;
- jitter when many clients could retry simultaneously.

Never infinite-retry a poison payload.

Retry policy must preserve idempotency.

---

# 15. Observability from day one

For each run/task capture:

- run ID;
- job/task;
- code version/commit;
- start/end;
- duration;
- source;
- rows read;
- rows written;
- rows rejected;
- checkpoint before/after;
- retries;
- failure category;
- freshness;
- relevant cost/bytes scanned when applicable.

Logs should answer:
- what happened?
- to which data?
- using which code?
- when?
- why did it fail?
- can I replay it safely?

Where appropriate, design metadata to be compatible with OpenLineage concepts:
- Job;
- Run;
- Dataset;
- input/output relationships.

---

# 16. Security and privacy

## 16.1 Least privilege

Every identity gets only:
- required resources;
- required actions;
- required duration.

Separate:
- human;
- CI/CD;
- orchestrator;
- application;
- agent identities.

## 16.2 Secrets

Never:
- commit secrets;
- print secrets;
- place secrets in agent instructions;
- store secrets in data artifacts.

## 16.3 PII

Classify before exposing.

Use:
- minimization;
- masking;
- hashing/tokenization where appropriate;
- access controls;
- retention policies;
- deletion mechanisms.

## 16.4 Broken-glass

Enterprise production systems may justify temporary emergency access.

For portfolio/small projects, demonstrate the principle in documentation rather than building unnecessary approval infrastructure.

---

# 17. Orchestration

Introduce an orchestrator when the project has:
- multiple dependent tasks;
- retries;
- scheduling;
- backfills;
- parameterized runs;
- visibility needs.

Do not use the orchestrator as:
- transformation engine;
- giant state database;
- place to hide business logic.

Tasks should invoke independently testable programs/models.

Prefer one primary orchestrator per platform unless a clear boundary justifies multiple.

---

# 18. CI/CD and reproducibility

Minimum engineering baseline:

- dependency lock;
- deterministic environment;
- lint/static checks;
- unit tests;
- transformation/data tests;
- contract validation;
- build/deploy separated from runtime;
- version-controlled configuration;
- no manual production-only edits.

A pipeline is not reproducible if only its creator knows the clicks required to run it.

---

# 19. Architecture Decision Records

Create an ADR when selecting or changing something that:

- materially changes architecture;
- creates a dependency;
- affects data compatibility;
- affects cost;
- affects security;
- is difficult to reverse.

ADR format:

1. Context
2. Decision
3. Alternatives considered
4. Consequences
5. Reversal/migration path

Do not create ADRs for trivial formatting decisions.

---

# 20. Agentic data architecture — 2026 addendum

## 20.1 Foundation before agent

An agent should sit on top of:
1. trusted data;
2. modeled data;
3. explicit semantics;
4. controlled access;
5. observability.

The LLM does not repair architectural ambiguity.

## 20.2 Context layer

Maintain version-controlled business context:

- glossary;
- entity definitions;
- metric definitions;
- relationships;
- ownership;
- freshness;
- known limitations;
- examples.

This context is as important as model choice for structured-data agents.

## 20.3 Semantic layer

Expose canonical:
- metrics;
- dimensions;
- time grains;
- join relationships;
- definitions.

Goal:
- BI, analysts and agents calculate the same metric the same way.

## 20.4 Read before write

Agent capability progression:

### Stage A — advisory
Agent sees documentation, no system access.

### Stage B — read-only
Agent can query certified resources/views.

### Stage C — proposed action
Agent prepares a write/change but a human approves.

### Stage D — bounded autonomous write
Agent can perform allowlisted, reversible actions within scope.

### Stage E — broader autonomy
Only after evidence, evals, logging, authorization and rollback exist.

Do not begin at Stage E.

## 20.5 MCP and tool interfaces

When exposing tools/resources:

- keep tools narrow;
- use explicit schemas;
- return bounded data;
- do not expose arbitrary SQL execution by default;
- authenticate user/agent;
- authorize per action/resource;
- audit every call;
- treat tool descriptions and external content as untrusted inputs;
- prevent credential/token passthrough;
- separate read and write tools.

## 20.6 Deterministic shell around non-deterministic intelligence

Agent decisions may be probabilistic.

System invariants should not be.

Use deterministic enforcement for:
- schema;
- allowed actions;
- money limits;
- access scopes;
- data contracts;
- validation;
- deployment checks;
- irreversible operations.

## 20.7 Evals are tests for agent behavior

Maintain evaluation cases for:
- tool selection;
- correct metric interpretation;
- stale-data behavior;
- refusal when unauthorized;
- malformed tool response;
- contradictory context;
- timeout/retry;
- safe escalation to human.

Re-run evals when:
- model changes;
- prompt/instructions change;
- tools change;
- schemas change;
- semantic definitions change.

## 20.8 Agent observability

Capture where policy allows:
- agent run;
- model;
- tool calls;
- tool latency;
- tool errors;
- token usage;
- retries;
- decisions requiring approval;
- outcome;
- evaluation result.

Prefer standardized telemetry concepts such as OpenTelemetry GenAI conventions where practical.

## 20.9 Context hygiene

Do not dump every file into an agent context.

Prefer:
- retrieval of relevant documentation;
- concise contracts;
- clear source-of-truth hierarchy;
- explicit current SDD/ADR;
- relevant schemas only.

More context can produce more confusion when sources conflict.

## 20.10 Agents and data quality

Acceptable:
- suggest new quality rules;
- classify unusual failures;
- summarize incidents;
- assist root-cause analysis;
- compare expected/actual schemas;
- draft remediation.

Do not let an LLM silently waive deterministic quality failures.

---

# 21. Architecture anti-patterns

Reject by default:

- Kafka for a daily batch with one consumer;
- Spark for MB/low-GB datasets that SQL/DuckDB handles comfortably;
- Kubernetes for a single local portfolio application;
- data lake without a concrete object-storage use case;
- microservices for a project that fits one deployable service;
- duplicated business metrics across dashboards;
- raw database access for an autonomous agent;
- unrestricted natural-language-to-SQL against production;
- using AI output as the sole data-quality gate;
- adding Medallion layers that do not establish new invariants;
- storing secrets in `.env` committed to Git;
- retrying every exception;
- swallowing exceptions and returning success;
- checkpoint advancement before durable commit;
- `SELECT *` in durable downstream models;
- timestamps without timezone policy;
- money in floating point;
- notebooks as the only production implementation;
- architectural decisions that exist only in chat history.

---

# 22. Architecture fitness score

Score each proposal 0–5.

| Dimension | Question |
|---|---|
| Problem fit | Does every major component map to a requirement? |
| Simplicity | Could this be materially simpler? |
| Correctness | Are grain, keys, contracts and semantics explicit? |
| Idempotency | Can work be retried/replayed safely? |
| Recoverability | Can we rebuild after failure? |
| Observability | Can we explain a run and trace data lineage? |
| Quality | Are structural, relational and business rules tested? |
| Security | Are access and secrets least-privilege? |
| Cost | Does architecture fit the budget? |
| Maintainability | Can another engineer understand and change it? |
| Agent readiness | Are context, semantics and controlled access available? |
| Learning/CV signal | Does the project demonstrate real engineering rather than tool collection? |

### Interpretation

- **50–60:** strong
- **40–49:** viable, inspect weak dimensions
- **30–39:** redesign likely needed
- **<30:** architecture is probably tool-driven or underspecified

A high score does not require many technologies.

---

# 23. Maturity ladder for portfolio/projects

## Level 1 — Reproducible pipeline
Demonstrate:
- Python/SQL;
- deterministic ingestion;
- schemas;
- tests;
- Git;
- local reproducibility.

## Level 2 — Production-shaped batch platform
Add:
- incremental loads;
- idempotency;
- raw/clean/consumer layers as justified;
- orchestration;
- quarantine;
- structured logging;
- dimensional modeling;
- data quality.

## Level 3 — Platform engineering
Add only if useful:
- CI/CD;
- IaC;
- cloud deployment;
- secret management;
- lineage;
- observability;
- SLAs.

## Level 4 — Distributed/real-time
Add only when workload justifies:
- CDC;
- event streaming;
- distributed processing;
- schema registry;
- event-time semantics.

## Level 5 — Agent-ready data product
Add:
- semantic/context layer;
- certified agent-accessible data;
- MCP/tools/resources;
- read-only first;
- authorization;
- agent evals;
- GenAI observability;
- controlled action surface.

---

# 24. Required structure of any future SDD

An agent using this bible must produce, at minimum:

1. Executive summary
2. Problem statement
3. Jobs to be done
4. Goals
5. Non-goals
6. Assumptions
7. Constraints
8. Stakeholders/consumers
9. Source systems
10. Functional requirements
11. Non-functional requirements
12. Data classification
13. Data contracts
14. Data model and grain
15. High-level architecture
16. Component responsibilities
17. End-to-end flows
18. Incremental/state strategy
19. Idempotency
20. Failure/retry/recovery
21. Data quality
22. Observability/lineage
23. Security/privacy
24. Deployment/reproducibility
25. Cost controls
26. Testing strategy
27. Backfill/reprocessing
28. Schema evolution
29. Agent-readiness, if applicable
30. Rejected alternatives
31. ADR list
32. Milestones
33. Acceptance criteria
34. Risks
35. Open questions

No implementation should begin if grain, state/checkpoint semantics, error behavior, and acceptance criteria remain ambiguous.

---

# 25. Compact prompt to feed an AI before requesting an SDD

Use this when the full bible cannot fit in context:

> Design from requirements, not from fashionable tools. Prefer the smallest architecture that meets correctness, reliability, latency, security and scale requirements. Default to batch, relational/SQL processing, explicit contracts, immutable raw evidence when replay is needed, idempotent incremental loads, deterministic checkpoints, data-quality gates, quarantine, observable run metadata, and least privilege. Introduce streaming, CDC, Spark, Kafka, lakes/lakehouses, Kubernetes, microservices or agent autonomy only when a stated requirement justifies their operational complexity. Define grain and business semantics before modeling. Centralize metrics. Treat schemas/contracts as versioned interfaces. Keep OLTP and OLAP workloads separated. Push filters/aggregations to the data engine instead of moving unnecessary data to application code. Design retries with timeouts/backoff and poison-data isolation. For agentic systems, build trusted data + semantic/context layers first, expose read-only certified resources before write tools, enforce authorization outside the prompt, audit tool calls, use deterministic guardrails around non-deterministic model behavior, and require evals. Every architecture decision must state the requirement it solves, alternatives considered, costs, failure modes, and reversal path. Do not write code until the SDD has explicit goals, non-goals, flows, contracts, state semantics, tests and acceptance criteria.

---

# 26. 2026 research synthesis

## What appears durable

Across current practitioner discussions and engineering guidance:

- Core DE fundamentals remain: SQL, data modeling, idempotency, data quality, lineage, reliability and domain knowledge.
- AI coding agents can increasingly generate transformations, dbt models and boilerplate, but production quality still depends heavily on explicit specifications and verification.
- Semantic/context layers are becoming more important because agents need business meaning, not merely schemas.
- Data contracts and freshness become more consequential when autonomous systems consume data.
- Observability must include both pipeline runs and agent/tool execution.
- "Read before write" is a strong operating principle for agent autonomy.
- Architecture simplification is actively valued; Medallion and data lakes are not universal mandates.
- The likely engineering advantage is not memorizing more tools but becoming better at defining constraints, interfaces, semantics, evaluation and failure behavior.

## What remains experimental / context-dependent

- Fully autonomous agent-written/maintained data platforms.
- LLMs as the sole data-quality authority.
- "Adaptive" agent-curated analytical layers.
- MCP as a universal replacement for conventional interfaces.
- Ontologies/knowledge graphs for every organization.
- Agentic ETL with no deterministic platform beneath it.

Treat these as experiments, not baseline requirements.

---

# 27. Source notes

This edition was informed by the following sources and contemporary practitioner discussions:

- Martin Fowler / Thoughtworks, *Making Your Data Ready for Agentic AI* (2026): https://martinfowler.com/articles/making-data-ready-for-agentic-ai.html
- Anthropic, *Building effective agents*: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *Demystifying evals for AI agents* (2026): https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, *Writing effective tools for agents*: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, *Trustworthy agents in practice* (2026): https://www.anthropic.com/research/trustworthy-agents
- Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-11-25
- OpenTelemetry, *GenAI Observability* (2026): https://opentelemetry.io/blog/2026/genai-observability/
- OpenLineage specification: https://openlineage.io/docs/spec/
- Bitol / Open Data Contract Standard: https://bitol.io/
- Thoughtworks Technology Radar, Data Contract CLI: https://www.thoughtworks.com/en-ec/radar/tools/data-contract-cli
- dbt Developer Hub / Semantic Layer: https://docs.getdbt.com/
- r/dataengineering discussions (2026) on Medallion, semantic layers, AI coding agents, data quality and data platform architecture.
