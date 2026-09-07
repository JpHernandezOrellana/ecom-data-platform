# ADR-004: Fulfillment mart grain, metrics, and publication

**Status:** Accepted  
**Date:** 2026-09-06  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Decision scope:** Phase 1  
**Related SDD:** `SDD.md`, Sections 17-20  

## Context

The first vertical slice must produce a useful Gold output from one incremental entity. Orders can support fulfillment analysis but cannot support GMV, AOV, product, seller, payment, or regional metrics without additional entities.

The source is Brazilian and its timestamps are naive. The intended analytical reporting context is Chilean. The mart must make its date role and timezone conversion explicit.

Incorrect published data has a higher cost for the portfolio narrative than one delayed local run. A failed dbt candidate must not replace the last tested Gold output.

## Decision

### Model and grain

Phase 1 publishes `mart_daily_order_fulfillment`.

One row represents one purchase-date cohort in `America/Santiago`. Outcome measures describe the latest known state of orders purchased on that date. They are not counts of status events or deliveries occurring on that date.

### Metrics

The mart contains:

- order count;
- delivered order count;
- canceled order count;
- late delivered order count;
- late-delivery eligible order count;
- late-delivery rate;
- average delivery duration in decimal days;
- orders with a documented fulfillment-quality issue.

Metric formulas and eligibility are canonical in `docs/metrics.md` and the Gold contract.

### Time semantics

Original timestamps are interpreted as `America/Sao_Paulo`, converted to UTC instants, then converted to `America/Santiago` to derive `reporting_date`. Durations and late comparisons use UTC instants.

### Publication

Each Gold candidate is an immutable versioned relation in `gold_candidate`. Required tests target that exact relation. After success, one warehouse transaction replaces the stable `gold.mart_daily_order_fulfillment` view and records publication metadata.

A failed candidate cannot become visible through the stable view. Candidate cleanup never deletes the published relation. Phase 1 retains the five most recent successful candidates and failed candidates for seven days.

## Alternatives considered

### Daily sales as the first mart

Rejected for Phase 1 because revenue requires at least order items and cancellation semantics. Calling an orders-only output a sales mart would be misleading.

### Delivery-date grain

Rejected because it would answer a different question and would not naturally include all purchased or canceled orders. Purchase-date cohorts better demonstrate mutable outcomes after incremental status updates.

### Order fact plus date dimension in Phase 1

Deferred because they add models without establishing an additional required invariant for the first single-entity output.

### Build directly into stable Gold

Rejected because a model can be replaced before a subsequent test fails, exposing untested output.

### Report source dates only

Rejected because the selected consumer context is Chilean. Source-local timestamps remain available in lower layers for traceability.

## Consequences

Positive consequences:

- the first mart is coherent with one source entity;
- grain and date role are unambiguous;
- late-delivery denominators are inspectable;
- incremental order updates can restate prior purchase cohorts;
- failed quality tests preserve the last certified output.

Costs and limitations:

- cohort results can change when an old order receives a new status;
- converting between Brazil and Chile can change the reporting date;
- Phase 1 has no monetary metrics;
- immutable candidates require local cleanup;
- this mart is not order-status event history.

## Reversal and migration path

Later phases add separate facts and marts rather than changing this grain to combine incompatible questions. Monetary marts require order items, explicit BRL definitions, and an accepted historical BRL-to-CLP conversion policy.
