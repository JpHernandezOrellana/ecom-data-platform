# ADR-005: Commerce metrics (GMV, AOV, freight, cancellations, refunds)

**Status:** Accepted
**Date:** 2026-10-04
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-04
**Decision scope:** Phase 2A/2B (order items, payments, synthetic refunds; BRL only)
**Related SDD:** `SDD.md`, Phase 2 roadmap; `docs/metrics.md`
**Related ADRs:** ADR-004 (fulfillment grain, unaffected), ADR-006 (composite cursor), ADR-007 (FX, deferred)

## Context

Phase 1 certified fulfillment metrics from `orders` alone. Phase 2 adds `order_items` and,
later, `order_payments`, enabling commerce-value metrics (GMV, AOV). Olist provides no
refund events: `payment_value` frequently disagrees with `price + freight_value` for
reasons unrelated to refunds (partial payments, installments, cancellations before full
payment, data entry). Inferring refunds from this disagreement, from `canceled` status, or
from voucher payments would invent business semantics the source does not support.

A decision is required before writing `int_order_commerce` or `mart_daily_commerce`:
what counts toward GMV, which order states are eligible, whether freight is included, and
how (or whether) refunds are represented.

## Decision

### GMV definition

```text
gmv_brl = sum(order_items.price)
```

over eligible order items only (see eligibility below). `freight_value` is **excluded**
from GMV. It is published separately:

```text
freight_value_brl = sum(order_items.freight_value)
gross_order_value_brl = gmv_brl + freight_value_brl
```

GMV never includes freight; a reader who wants merchandise value plus shipping uses
`gross_order_value_brl` explicitly. These are never relabeled as "revenue."

### Order eligibility

An order is eligible for canonical `gmv_brl` and `aov_brl` if its latest known
`order_status` is **not** `canceled` and **not** `unavailable`. All other statuses
(`created`, `approved`, `processing`, `invoiced`, `shipped`, `delivered`) are eligible.

Excluded orders are not dropped silently. The mart separately reports:

```text
canceled_item_value_brl
unavailable_item_value_brl
```

so a reader can reconstruct gross-of-exclusions totals if needed.

### AOV definition

```text
aov_brl = gmv_brl / count(distinct order_id) over the same eligible order set
```

The denominator counts distinct eligible orders that have at least one item — never item
rows, never payment rows. If the denominator is zero for a cohort, `aov_brl` is `NULL`,
not zero and not undefined-as-error.

### Refunds

Olist contains no refund events. Phase 2B introduces a **clearly labeled synthetic refund
event source** (see "Synthetic refunds" below) built after `order_payments` exists, not
before. Until that source exists, refunds are not computed, estimated, or implied by any
other signal:

- `canceled` status is not treated as a refund.
- A payment/item-value mismatch is not treated as a refund.
- Voucher payment type is not treated as a refund.
- An order without items is not treated as a refund.

`gmv_brl` is documented as **gross of unobserved refunds** until the synthetic refund
source is accepted and implemented.

### Synthetic refunds (Phase 2B, after payments)

A deterministic, clearly-labeled synthetic generator (parallel to `ecom.mutate`) appends
refund events to a dedicated operational table, each referencing an existing
`(order_id, payment_sequential)` and carrying `refund_id`, `refunded_amount`,
`refund_reason`, and `refunded_at`. These are synthetic test/demo fixtures, not inferred
history, and are documented as such everywhere they appear (contract, mart description,
`docs/metrics.md`).

Refunds are reported in a **separate mart, grained by refund date** (not by order
purchase date), e.g. `mart_daily_refunds`, with `refunded_amount_brl` and `refund_count`.
`mart_daily_commerce.gmv_brl` is never reduced by refunds. A reader who wants a net figure
computes it explicitly from both marts:

```text
net_payment_value_brl = payment_value_brl - refunded_amount_brl
```

This is reported as `net_payment_value_brl` in a payments-grained context, never as a
replacement for `gmv_brl`.

### Payments are not the GMV authority

`order_payments.payment_value` is used for payment-method analysis and for reconciliation
diagnostics against `price + freight_value` (surfacing the known structural mismatches
documented in this ADR's research), never as the basis for GMV.

### Currency and date

`mart_daily_commerce` uses the same cohort grain as `mart_daily_order_fulfillment`: one row
per purchase-date cohort in `America/Santiago`, derived the same way (source-local
`America/Sao_Paulo` timestamp -> UTC instant -> `America/Santiago` date). All amounts in
this ADR's scope are BRL only; CLP conversion is deferred to ADR-007 and is additive
(extra columns), never a silent replacement of BRL figures.

## Alternatives considered

### Include freight in GMV

Rejected. Freight is a logistics pass-through cost, not merchandise value; conflating them
would misstate a standard e-commerce KPI and contradict how GMV is normally read by anyone
reviewing the portfolio.

### Include `canceled`/`unavailable` orders in GMV

Rejected as the canonical definition because it would overstate realized commerce value.
Retained as separate diagnostic totals so no information is discarded.

### Derive refunds from `canceled` status or payment/item mismatch

Rejected. Both signals have multiple non-refund explanations in this dataset (see profiling
notes referenced from `docs/CURRENT_STATE.md`); treating them as refunds would be inventing
business semantics not supported by source evidence, which `AGENTS.md` §20 prohibits.

### Use `payment_value` as the GMV basis

Rejected. Payments do not reconcile with items+freight for ~1.3% of orders for reasons
unrelated to merchandise value (partial/installment payments, timing), and payments contain
no per-product breakdown needed for commerce KPIs.

### Skip refunds entirely (no mart)

Rejected. A portfolio project demonstrating realistic e-commerce analytics should show how
refunds would be modeled once a real signal exists; a clearly labeled synthetic source
demonstrates the modeling pattern without claiming it is observed history.

## Consequences

Positive:

- GMV and AOV are unambiguous, auditable, and reproducible from `order_items` alone;
- excluded-order value is never silently dropped, only separated;
- refund reporting is modeled without inventing unsupported semantics;
- BRL-only scope keeps this ADR independent of the FX source decision.

Costs and limitations:

- `gmv_brl` is gross of real-world refunds that Olist does not expose; this must stay
  visible in every place the metric is documented;
- synthetic refunds are demo fixtures, not a substitute for a real refund feed, and must
  never be described as observed Olist history;
- `mart_daily_commerce` and `mart_daily_refunds` must be read together for a "net" view;
  no single column provides it.

## Reversal and migration path

If a real refund signal becomes available in a later phase, the synthetic generator is
retired, the contract is versioned, and `mart_daily_refunds` is repointed to real events
without changing its grain or column names. GMV/AOV definitions in this ADR do not change
unless a new ADR explicitly revises them.
