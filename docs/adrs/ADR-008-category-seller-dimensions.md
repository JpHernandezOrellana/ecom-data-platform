# ADR-008: Products/sellers dimensions and category commerce mart (Phase 2C slice 1)

**Status:** Accepted
**Date:** 2026-10-05
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-05
**Decision scope:** Phase 2C slice 1 (`products`, `sellers`, `mart_daily_category_commerce`)
**Related SDD:** `SDD.md`, Phase 2 roadmap; `docs/CURRENT_STATE.md`
**Related ADRs:** ADR-002 (cursor/commit/checkpoint protocol, reused unchanged),
ADR-004 (Gold publication pattern, reused unchanged), ADR-005 (commerce eligibility and
GMV/freight exclusion rules, reused unchanged for the category breakdown)

## Context

Phase 2A/2B certified order-level and payment-level commerce metrics. Phase 2C's entry
work (per `SDD.md` roadmap and `docs/CURRENT_STATE.md` §8) is category/seller analytics
and the `customer_id` vs `customer_unique_id` distinction. This ADR scopes the first 2C
slice narrowly: `products` and `sellers` as ingested dimensions, and one new certified
Gold mart breaking commerce value down by product category. `customers` and any
new-vs-returning-customer semantics are explicitly deferred (see "Deferred" below) because
`SDD.md` §37 already marks customer-history strategy as a decision not yet accepted, and
inventing it here would violate `AGENTS.md` §20.

`olist_products_dataset.csv` (32,951 rows) and `olist_sellers_dataset.csv` (3,095 rows)
have no business timestamp and no status domain — unlike `orders`, they are plain
dimension tables. The source-profile check run before this ADR confirms zero orphan
`product_id`/`seller_id` references from `order_items` in the full Olist dataset
(`contracts/source/olist_order_items.v1.yaml`'s `observed_profile`), but 610 products have
a null `product_category_name`.

## Decision

### Ingestion pattern: reuse ADR-002 unchanged, not ADR-006

`products` and `sellers` each have a single-column natural key (`product_id`,
`seller_id`), so they follow the plain ADR-002 cursor/commit/checkpoint/recovery protocol
used by `orders` — not ADR-006's composite-key padding, which does not apply here. Each
gets its own simulated `source_created_at`/`source_updated_at` pair at bootstrap time,
identical in spirit to `orders` (`docs/CURRENT_STATE.md`'s "no business timestamp exists"
pattern already established for `order_payments`). Each entity is its own
`entity_name` in `control.checkpoint`/`control.batch`; no schema change to `control.*`.

### Quality scope is intentionally narrower than `orders`

`products`/`sellers` have no status domain and no business timestamp to validate.
Row-level validation is limited to: primary key present and pattern-matching, and
duplicate-key rejection at bootstrap (mirroring `OLIST-ORD-KEY-001`/`002`). A null
`product_category_name` is **not** a quality violation — it is a known, expected source
characteristic (610 rows) and is carried through, never quarantined for that reason alone.

### Category translation is a dbt seed, not an ingested entity

`product_category_name_translation.csv` (71 rows) is static reference data with no
natural incremental semantics (no key mutates, no cursor applies). Running it through the
full bootstrap/extract/load/checkpoint machinery would add ingestion ceremony with no
corresponding invariant to protect (`AGENTS.md` §5: "Do not scaffold five unused
technologies in advance" applies equally to over-scaffolding one). It is loaded as a dbt
seed (`dbt/seeds/product_category_name_translation.csv`) and joined in Silver.

### New Gold mart: `mart_daily_category_commerce`

Grain: one row per `(reporting_date, product_category_name)`, where `reporting_date` is
the same purchase-date cohort (`America/Santiago`) as `mart_daily_commerce`, and
`product_category_name` is the product's category **at item grain**, not pre-aggregated
to order grain (an order may contain items from multiple categories, so order-level
pre-aggregation — the `int_order_commerce` pattern — is not reusable here).

Eligibility and monetary rules are **identical to ADR-005**, reapplied at item grain
instead of order grain:

- an item is eligible when its order's latest status is not `canceled`/`unavailable`;
- `category_gmv_brl = sum(price)` over eligible items in the category cohort, freight
  excluded and reported separately as `category_freight_value_brl`;
- a product whose `product_category_name` is null is bucketed as the literal string
  `'unknown'`, never dropped;
- `category_gmv_brl` summed across all categories for one `reporting_date` must equal
  `mart_daily_commerce.gmv_brl` for that same date — this is a blocking reconciliation
  test, since the two marts slice the same eligible item population two different ways.

### Orphan products/sellers referenced by order_items

An `order_items` row whose `product_id` is absent from `stg_products` fails the dbt build
(`assert_no_orphan_order_item_products`), the same no-silent-loss pattern as
`GOLD-COM-ORPHAN-001`, and is distinct from a product that exists but has a null category
(which is valid and bucketed as `'unknown'`). `seller_id` orphans are checked the same way
for symmetry, even though no Gold metric currently groups by seller.

### Currency and date

BRL only, same as ADR-005; no CLP column exists until Phase 2D (ADR-007).

## Alternatives considered

### Pre-aggregate category commerce from `int_order_commerce`

Rejected: `int_order_commerce` is already aggregated to one row per order, discarding
item-level category attribution. Reusing it would force an incorrect assumption that one
order has one category.

### Ingest `product_category_name_translation` through the full entity pipeline

Rejected: it has no natural key mutation, no cursor, and no quarantine-worthy row shape;
running it through bootstrap/extract/load/checkpoint machinery built for mutable
operational entities would add indirection with no invariant it protects.

### Treat a null `product_category_name` as a quarantine violation

Rejected: it is a documented, expected source characteristic (610 rows across the full
dataset), not a structural or business-rule violation. Quarantining it would misrepresent
normal source data as an error.

### Include `customers` in this same slice

Rejected for this slice: `customer_id` vs `customer_unique_id` and any
new-vs-returning-customer metric require an accepted historical/dedup definition that
`SDD.md` §37 explicitly defers. Bundling it here would force an unreviewed business-
semantics decision into an unrelated dimension-ingestion change.

## Consequences

Positive:

- category/seller dimensions reuse the exact ADR-002 protocol with zero `control.*`
  schema changes;
- `mart_daily_category_commerce` is independently reconcilable against the already
  certified `mart_daily_commerce`;
- no new architecture, orchestrator, or storage engine introduced (`AGENTS.md` §3).

Costs and limitations:

- `seller_id` orphan checking exists without yet having a seller-grained Gold consumer;
  it is forward-looking evidence hygiene, not speculative metric design;
- `customers` and category-based seller performance metrics remain out of scope for this
  slice and require their own ADR before implementation.

## Deferred

- `customers` ingestion and the `customer_id`/`customer_unique_id` distinction (Phase 2C
  slice 2 or later, pending an accepted customer-history ADR).
- Seller-grained Gold marts (e.g. seller performance/leaderboards) — `sellers` is ingested
  and orphan-checked in this slice, but no seller-grained metric is certified yet.
- Geolocation canonicalization (separately deferred per `docs/CURRENT_STATE.md` §5).
