# Metric Glossary

**Version:** 1.1.0<br>
**Status:** Accepted  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Initial accepted date:** 2026-09-06<br>
**Last synchronized:** 2026-10-05<br>
**Applies to:** `mart_daily_order_fulfillment`, `mart_daily_commerce`, and `mart_daily_refunds`<br>
**Related design:** `SDD.md`, Sections 18-20; ADR-004; ADR-005<br>

## Shared semantics

### Fulfillment mart grain

One row represents one order purchase-date cohort in `America/Santiago`.

The mart describes the latest known outcomes of orders purchased on each date. It does not describe deliveries or status-change events that occurred on that date.

### Source time interpretation

Olist timestamps are timezone-naive. Phase 1 interprets them as `America/Sao_Paulo`, converts them to UTC instants, and uses `America/Santiago` only for the reporting-date projection.

An ambiguous Sao Paulo local timestamp uses IANA `fold=0` and carries a provenance flag. A nonexistent local timestamp is quarantined. Durations and timestamp comparisons use UTC instants, not naive local values.

### Structurally accepted order

An order that passed the applicable bootstrap and operational ingestion contracts and is represented by the deterministic latest source version in `silver.stg_orders`.

Known business-quality flags do not remove an order from `order_count`. Individual outcome metrics apply their own eligibility rules.

## Fulfillment metrics

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

## Fulfillment mart exclusions

`mart_daily_order_fulfillment` does not define or publish:

- GMV;
- revenue;
- average order value;
- freight totals;
- payment totals;
- refunds;
- BRL-to-CLP conversion;
- product, seller, customer, or geographic metrics.

These do not belong to the fulfillment mart's grain. Payment value, item value, and
accounting revenue are not assumed to be interchangeable.

## Commerce mart semantics

### Commerce mart grain

`gold.mart_daily_commerce` has one row per order purchase-date cohort in
`America/Santiago`. It uses the same `reporting_date` derivation as
`mart_daily_order_fulfillment`.

All commerce amounts are source-currency BRL. CLP columns do not exist in this mart yet;
their additive implementation is deferred to Phase 2D under ADR-007.

An order is eligible for canonical commerce metrics when its latest known status is
neither `canceled` nor `unavailable` and it has at least one item. Excluded item values
remain visible in separate diagnostic metrics.

### Eligible order count

**Column:** `eligible_order_count`<br>
**Definition:** Count of distinct eligible `order_id` values with at least one item.<br>
**Exclusion:** Orders whose latest status is `canceled` or `unavailable`.<br>

### GMV

**Column:** `gmv_brl`<br>
**Definition:** Sum of `order_items.price` over eligible orders.<br>
**Currency/type:** BRL fixed-precision decimal.<br>
**Exclusions:** Freight, canceled orders, unavailable orders, and refunds.<br>
**Naming:** GMV is never relabeled as revenue.<br>

```text
sum(order_items.price) over eligible orders
```

### Freight value

**Column:** `freight_value_brl`<br>
**Definition:** Sum of `order_items.freight_value` over eligible orders.<br>
**Relationship to GMV:** Reported separately and never included in `gmv_brl`.<br>

### Gross order value

**Column:** `gross_order_value_brl`<br>
**Definition:** Merchandise GMV plus freight over the same eligible order set.<br>
**Naming:** Never called revenue.<br>

```text
gmv_brl + freight_value_brl
```

### Average order value

**Column:** `aov_brl`<br>
**Definition:** GMV divided by distinct eligible orders with at least one item.<br>
**Zero denominator:** Null.<br>

```text
gmv_brl / eligible_order_count
```

### Excluded item values

**Columns:** `canceled_item_value_brl`, `unavailable_item_value_brl`<br>
**Definition:** Sum of item price for orders whose latest status is respectively
`canceled` or `unavailable`.<br>
**Purpose:** Diagnostic visibility; both values are excluded from canonical `gmv_brl`.<br>

## Refund mart semantics

### Synthetic-source warning

Olist contains no refund event signal. Every row underlying
`gold.mart_daily_refunds` is generated synthetic demo data, not observed Olist history.
Synthetic refunds must remain labeled as such in contracts, models, evidence, and
consumer-facing descriptions.

### Refund mart grain

`gold.mart_daily_refunds` has one row per refund-date cohort. `reporting_date` is the
calendar date of `refunded_at` in `America/Santiago`, not the original order's purchase
date.

The refund and commerce marts therefore have different date roles. They must not be
merged by date without an explicit consumer join and an explicit interpretation of that
join.

### Refund count

**Column:** `refund_count`<br>
**Definition:** Count of synthetic refund events in the refund-date cohort.<br>
**Null behavior:** Not nullable and non-negative.<br>

### Refunded amount

**Column:** `refunded_amount_brl`<br>
**Definition:** Sum of synthetic `refunded_amount` values in the refund-date cohort.<br>
**Currency/type:** BRL fixed-precision decimal.<br>
**Constraint:** A refund may not exceed the referenced payment value.<br>

### Relationship to commerce GMV

`mart_daily_commerce.gmv_brl` is never reduced by `refunded_amount_brl`. A consumer that
needs a net payment view must compute it explicitly in a payments-grained context; that
result is not a replacement for GMV.

## Payment reconciliation

`silver.int_payment_reconciliation` is diagnostic only. `order_payments.payment_value`
may be compared with item price plus freight, but it is never the authority for GMV and a
disagreement is not interpreted as a refund.

## Change policy

A change to grain, status eligibility, denominator, formula, timestamp interpretation,
date role, duration unit, currency treatment, synthetic-source labeling, or quality-flag
inclusion requires:

- a new metric version;
- a synchronized Gold contract update;
- updated tests;
- an ADR and SDD update when the semantic change is material.
