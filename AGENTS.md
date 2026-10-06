# AGENTS.md
## Operating Rules for AI Coding Agents — E-commerce Data Platform

This file governs AI-assisted work in this repository.

The project is a Data Engineering portfolio system designed to demonstrate production-shaped engineering. Agents must optimize for **correctness, simplicity, reproducibility, explainability and learning value**, not for maximum implementation speed or maximum tool count.

---

# 1. Source-of-truth hierarchy

When instructions conflict, use this order:

1. explicit current user request;
2. `docs/CURRENT_STATE.md` for current progress, active phase, next work and open
   limitations only;
3. accepted `SDD.md` for architecture and design;
4. accepted ADRs for scoped decisions;
5. data contracts / metric definitions for interfaces and business semantics;
6. this `AGENTS.md`;
7. repository README/task notes;
8. implementation details.

Dated evidence is authoritative for the execution it records, not for current project
progress. `docs/CURRENT_STATE.md` does not override accepted design, decisions, contracts,
or metric semantics.

Do not silently override a higher-priority artifact.

If an architectural request conflicts with the SDD, propose/update an ADR before implementing the change.

---

# 2. Mandatory reading before implementation

Before modifying project code, always read first:

- `docs/CURRENT_STATE.md` — current phase, invariants, open decisions, task-specific routing.

Then read the relevant:

- `SDD.md`;
- current ADRs;
- data contracts;
- metric glossary;
- existing tests for the touched component;
- README instructions.

Do not infer project architecture from filenames alone.

---

# 3. No architecture-by-agent improvisation

The agent must not introduce a new major dependency, database, broker, framework, cloud service or architecture pattern without an accepted design reason.

Examples requiring explicit approval/ADR:

- Kafka;
- Spark;
- Kubernetes;
- Redis;
- new orchestrator;
- new database;
- new cloud service;
- vector database;
- MCP server;
- autonomous write-capable agent.

"Modern", "best practice", "scalable" or "industry standard" are not sufficient justifications.

---

# 4. Work protocol

For non-trivial changes:

1. inspect relevant artifacts/code;
2. restate the target behavior;
3. identify affected invariants;
4. produce a concise implementation plan;
5. identify tests before implementation;
6. implement the smallest coherent change;
7. run targeted tests;
8. run broader relevant tests;
9. summarize evidence and remaining risks.

Do not declare success without verification.

---

# 5. Preserve the vertical-slice strategy

Prefer completing one end-to-end path over creating many incomplete components.

Example preferred order:

`source -> ingestion -> Bronze -> Silver -> Gold -> tests`

for one entity/use case before expanding breadth.

Do not scaffold five unused technologies in advance.

---

# 6. Data engineering invariants

The following are hard defaults.

## 6.1 Idempotency
Reprocessing the same logical input must not duplicate canonical facts.

## 6.2 Checkpoints
Never advance a source checkpoint before the associated data is durably persisted and the relevant ingestion stage has succeeded.

## 6.3 Stable keys
Do not invent unstable keys from row order.

## 6.4 Grain
Every fact/mart model must document its grain.

## 6.5 Money
Use fixed-precision decimal semantics, not float.

## 6.6 Time
Use the repository's explicit timezone policy. Do not mix naive and aware timestamps.

## 6.7 Raw immutability
Do not destructively rewrite accepted Bronze history merely to simplify downstream code.

## 6.8 No silent loss
Invalid data must be rejected/quarantined or fail explicitly. Never silently discard unexpected rows.

## 6.9 No hidden success
Do not catch broad exceptions and return a successful status.

## 6.10 No downstream `SELECT *`
Durable analytical models must select explicit fields unless the SDD/ADR states otherwise.

---

# 7. Incremental ingestion rules

When implementing incremental extraction:

- use deterministic cursor semantics;
- prefer `(updated_at, primary_key)` when timestamps are the cursor;
- define inclusive/exclusive boundary behavior;
- make retry safe;
- record cursor before/after;
- do not assume timestamps are unique;
- explicitly handle late-arriving records;
- test rerun behavior.

Do not implement "last timestamp" logic without boundary tests.

---

# 8. Source protection

The operational PostgreSQL database represents an OLTP source.

Do not:
- run broad analytical aggregations against it;
- use source DB as the final dashboard warehouse;
- introduce full-table scans into regular ingestion without justification.

Extraction queries must retrieve only required columns/rows where possible.

---

# 9. Validation and contracts

At ingestion boundaries:

- validate required schema/types;
- record contract/schema version where designed;
- fail closed on breaking structural changes;
- quarantine row-level bad data when safe;
- make validation deterministic.

An LLM recommendation may suggest a quality rule but cannot waive a contract failure by itself.

---

# 10. dbt / transformation rules

dbt models must:

- have a clear purpose;
- document grain;
- avoid duplicated business definitions;
- keep staging mechanical where possible;
- place canonical business metrics in appropriate Gold/semantic definitions;
- include relevant tests;
- avoid unnecessary chained models.

Before adding another transformation layer, answer:
"What invariant becomes true here?"

---

# 11. SQL rules

Favor:

- explicit column lists;
- readable CTEs;
- deterministic joins;
- appropriate predicates;
- database-side filtering/aggregation;
- documented grain;
- stable ordering only when ordering is semantically required.

Avoid:

- accidental Cartesian joins;
- `SELECT *` in durable models;
- implicit type coercion relied upon for correctness;
- pulling large tables into Python for operations SQL can perform directly.

---

# 12. Python rules

Target clear production-shaped Python.

Prefer:

- small cohesive modules;
- typed interfaces where useful;
- explicit configuration;
- pure/deterministic functions for transformation logic;
- structured exceptions;
- dependency injection for external boundaries when it improves testing.

Avoid:

- giant scripts;
- hidden global mutable state;
- hard-coded credentials;
- hard-coded local absolute paths;
- broad `except Exception: pass`;
- unnecessary OOP abstractions;
- clever code that reduces readability.

Use the project's selected formatter/linter/test conventions once configured.

---

# 13. Dependency policy

Before adding a dependency:

1. state what problem it solves;
2. check whether standard library/current dependency already solves it;
3. assess maintenance cost;
4. assess license/security;
5. pin it appropriately.

Do not add dependencies for trivial helpers.

Use stable releases, not alpha/beta versions, unless an accepted ADR requires experimentation.

---

# 14. Testing requirements

A change is incomplete without appropriate tests.

## Required categories as applicable

- unit;
- integration;
- data/dbt;
- contract;
- idempotency;
- failure/recovery.

Critical logic requiring explicit tests:
- cursor boundaries;
- checkpoint behavior;
- deduplication;
- type/schema validation;
- business metric definitions;
- quarantine;
- backfills;
- money/time handling.

---

# 15. Failure injection

When practical, deliberately test:

- source unavailable;
- timeout;
- malformed row;
- duplicate row;
- invalid foreign key;
- breaking schema;
- warehouse unavailable;
- crash before checkpoint commit.

The system should fail predictably, not merely work on the happy path.

---

# 16. Observability rules

Each run/task should preserve enough context to answer:

- what ran?
- when?
- with which run ID?
- which source/entity?
- what cursor/window?
- how many rows?
- how many rejected?
- did tests pass?
- what failed?
- can it be replayed?

Do not log secrets or unnecessary PII.

---

# 17. Reproducibility

Do not create undocumented manual steps.

Any setup step required to reproduce the project must become:

- version-controlled configuration;
- documented command/process;
- automated setup where appropriate.

A recruiter/reviewer should not need the original developer's laptop state.

---

# 18. Resource discipline

This is a local-first project.

Do not:
- start services that are not needed for the current task;
- add distributed services for future hypothetical phases;
- create intentionally huge test datasets when smaller fixtures prove correctness;
- make a local test suite depend on paid cloud resources.

Optimize first for correctness at representative scale.

Performance/load experiments should be isolated from normal tests.

---

# 19. Security rules

Never:
- commit secrets;
- echo tokens/passwords;
- place secrets in docs/prompts;
- grant unrestricted write access when read access suffices;
- expose future agent tools with broad arbitrary execution by default.

Use environment-based/configured secret injection when implementation begins.

---

# 20. Agent-specific safety

AI agents are non-deterministic collaborators.

The agent must:

- use repository artifacts as ground truth;
- not invent business semantics;
- not silently change metric definitions;
- not create new architecture because it is easier for the agent;
- verify generated SQL/code with tests;
- keep patches bounded to the task;
- clearly report assumptions;
- surface contradictions between docs and code.

If uncertain about a business definition, preserve the current canonical definition and flag the ambiguity rather than inventing a new one.

---

# 21. Context discipline

Do not load or summarize the entire repository if only a few files are relevant.

Prefer:
- current SDD section;
- relevant ADR;
- contract;
- touched module;
- tests;
- metric definition.

Avoid mixing obsolete drafts with accepted specifications.

---

# 22. Documentation requirements

Update documentation when behavior changes.

A meaningful change may require updates to:

- README;
- SDD;
- ADR;
- data contract;
- metric glossary;
- operational/runbook notes.

Code and architecture documentation must not knowingly diverge.

---

# 23. ADR trigger

Stop implementation and create/propose an ADR when a change:

- alters the ingestion pattern;
- changes checkpoint semantics;
- changes storage format;
- changes warehouse engine;
- changes orchestration;
- adds CDC/streaming;
- changes Gold grain;
- changes metric semantics;
- introduces agent write access;
- materially changes privacy/security;
- creates notable vendor/tool lock-in.

---

# 24. Agentic extension rules

When an AI analytics/operations layer is eventually introduced:

1. expose certified Gold/semantic resources first;
2. prefer read-only access;
3. provide explicit tool schemas;
4. do not expose unrestricted production SQL by default;
5. apply least privilege outside prompts;
6. audit tool calls;
7. maintain agent evals;
8. require human approval for consequential writes until proven safe;
9. keep deterministic validation around actions;
10. preserve rollback/recovery.

MCP is a possible interface, not an automatic architectural requirement.

---

# 25. Definition of done

A task is "done" only when:

- target behavior exists;
- relevant tests pass;
- failure behavior is considered;
- no prohibited secrets/configuration were introduced;
- docs/contracts are consistent;
- architecture was not silently changed;
- evidence can be shown.

"Code was generated" is not evidence.

---

# 26. Prohibited shortcuts

Do not:

- mock away the core behavior being demonstrated;
- replace incremental processing with full rebuild just to pass a demo;
- disable tests to make CI green;
- swallow invalid rows;
- mutate raw history;
- embed business metrics in dashboard-only SQL;
- introduce paid dependencies into the zero-cost MVP;
- claim "exactly once" without proving semantics;
- claim "real-time" without a latency requirement and measurement;
- claim scalability based only on using distributed tools.

---

# 27. Preferred agent posture

Act as a careful senior engineer reviewing a junior-to-mid portfolio project:

- challenge unnecessary complexity;
- protect invariants;
- explain consequential decisions;
- generate code only after design is accepted;
- optimize for maintainability and teachability;
- leave the repository in a more understandable state than before.
