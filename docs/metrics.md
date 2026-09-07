# Metric Glossary

**Version:** 1.0.0  
**Status:** Accepted  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Applies to:** Phase 1 `mart_daily_order_fulfillment`  
**Related SDD:** `SDD.md`, Sections 18-20  

## Shared semantics

### Mart grain

One row represents one order purchase-date cohort in `America/Santiago`.

The mart describes the latest known outcomes of orders purchased on each date. It does not describe deliveries or status-change events that occurred on that date.

### Source time interpretation

Olist timestamps are timezone-naive. Phase 1 interprets them as `America/Sao_Paulo`, converts them to UTC instants, and uses `America/Santiago` only for the reporting-date projection.

An ambiguous Sao Paulo local timestamp uses IANA `fold=0` and carries a provenance flag. A nonexistent local timestamp is quarantined. Durations and timestamp comparisons use UTC instants, not naive local values.

### Structurally accepted order

An order that passed the applicable bootstrap and operational ingestion contracts and is represented by the deterministic latest source version in `silver.stg_orders`.

Known business-quality flags do not remove an order from `order_count`. Individual outcome metrics apply their own eligibility rules.

## Metrics

### Order count

**Column:** `order_count`  
**Definition:** Count of distinct structurally accepted `order_id` values in the reporting-date cohort.  
**Statuses included:** All eight accepted statuses.  
**Null behavior:** Not nullable; zero is valid.  

```text
count(distinct order_id)
```

### Delivered order count

**Column:** `delivered_order_count`  
**Definition:** Count of distinct orders with delivered status and a valid non-negative purchase-to-customer-delivery interval.  
**Eligibility:** `order_status = delivered`, customer-delivery instant is non-null, and customer delivery is not earlier than purchase.  
**Exclusion:** A delivered status without a valid delivery instant remains visible as a quality issue but is not counted as delivered.  

```text
count(distinct order_id)
where order_status = delivered
  and order_delivered_customer_at is not null
  and order_delivered_customer_at >= order_purchase_at
```

### Canceled order count

**Column:** `canceled_order_count`  
**Definition:** Count of distinct orders where `order_status = canceled`.  
**Refund assumption:** No refund inference is made in Phase 1.  

```text
count(distinct order_id)
where order_status = canceled
```

### Late delivered order count

**Column:** `late_delivered_order_count`  
**Definition:** Count of delivered-eligible orders whose customer-delivery instant is later than the estimated-delivery instant.  
**Comparison:** Strictly greater than; equality is on time.  

```text
count(distinct order_id)
where delivered_eligible
  and order_estimated_delivery_at is not null
  and order_delivered_customer_at > order_estimated_delivery_at
```

### Late-delivery eligible order count

**Column:** `late_delivery_eligible_order_count`  
**Definition:** Count of delivered-eligible orders with a non-null estimated-delivery instant.  
**Purpose:** Explicit denominator for late-delivery rate.  

```text
count(distinct order_id)
where delivered_eligible
  and order_estimated_delivery_at is not null
```

### Late-delivery rate

**Column:** `late_delivery_rate`  
**Definition:** Late delivered orders divided by late-delivery eligible orders.  
**Type:** Fixed-precision decimal.  
**Zero denominator:** Null, not zero.  

```text
late_delivered_order_count
/
late_delivery_eligible_order_count
```

### Average delivery duration

**Column:** `average_delivery_duration_days`  
**Definition:** Average elapsed UTC time from purchase to customer delivery over delivered-eligible orders.  
**Unit:** Decimal days where one day is exactly 86,400 elapsed seconds.  
**Zero eligible orders:** Null.  

```text
average(
  elapsed_seconds(order_purchase_at, order_delivered_customer_at)
  / 86400
)
where delivered_eligible
```

### Orders with fulfillment-quality issue

**Column:** `orders_with_fulfillment_quality_issue`  
**Definition:** Count of distinct orders in the cohort with at least one documented lifecycle-quality flag.  

Initial included flags:

- delivered status without customer-delivery timestamp;
- customer delivery before purchase;
- customer delivery before carrier handoff when both are present;
- carrier handoff before approval when both are present.

Timezone-resolution provenance such as `ambiguous_fold_0` is reported separately and is not, by itself, a fulfillment-quality issue.

## Reporting date

**Column:** `reporting_date`  
**Role:** Grain key and purchase-cohort date.  

```text
olist purchase text
-> interpret in America/Sao_Paulo
-> convert to UTC instant
-> convert to America/Santiago
-> take local calendar date
```

Changing the timezone or date role is a breaking metric change.

## Phase 1 exclusions

Phase 1 does not define or publish:

- GMV;
- revenue;
- average order value;
- freight totals;
- payment totals;
- refunds;
- BRL-to-CLP conversion;
- product, seller, customer, or geographic metrics.

These require additional source entities and accepted Phase 2 definitions. Payment value, item value, and accounting revenue are not assumed to be interchangeable.

## Change policy

A change to grain, status eligibility, denominator, timestamp interpretation, date role, duration unit, or quality-flag inclusion requires:

- a new metric version;
- a synchronized Gold contract update;
- updated tests;
- an ADR and SDD update when the semantic change is material.
