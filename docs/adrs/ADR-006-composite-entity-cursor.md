# ADR-006: Composite natural-key cursor for multi-row-per-order entities

**Status:** Accepted
**Date:** 2026-10-04
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-04
**Decision scope:** Phase 2A onward, any entity whose natural key is composite
**Related SDD:** `SDD.md`, Sections 13-15, 23-25
**Related ADRs:** Extends ADR-002 (incremental cursor, batch commit, and recovery protocol)

## Context

ADR-002 defines the cursor, batch identity, and recovery protocol for `orders`, whose
natural key is the single column `order_id`. `order_items` has a composite natural key,
`(order_id, order_item_id)`, with no uniform mutation timestamp of its own (same
simulator-added `source_updated_at` pattern as orders). `control.checkpoint` and
`control.batch` already store cursor position generically as
`(cursor_updated_at, cursor_key)` with `cursor_key text` and are already partitioned by
`entity_name`, so no schema change is required — only a documented, contractual rule for
how a composite key becomes one `cursor_key` string.

Without an explicit rule, a future implementer could serialize the composite key
ad hoc (e.g. simple string concatenation), risking incorrect lexicographic ordering or
collisions (e.g. `order_item_id` 1 vs 10 vs 2 sorting wrong, or a separator appearing
inside an ID). ADR-002 is explicitly scoped to Phase 1/`orders`; extending its protocol to
a new entity shape requires its own decision record per `AGENTS.md` §23 (changes to
checkpoint/cursor semantics require an ADR).

## Decision

### Cursor shape (unchanged from ADR-002)

```text
(source_updated_at, source_cursor_key) — lower-exclusive, upper-inclusive, fixed upper
bound from one stable snapshot, identical recovery and checkpoint-advance protocol.
```

### Composite key serialization

For `order_items`:

```text
source_cursor_key = order_id || ':' || lpad(order_item_id::text, 4, '0')
```

Rules:

- `order_id` is a fixed-length UUID-like string in this dataset (32 hex chars) and never
  contains `:`; the separator is unambiguous.
- `order_item_id` is zero-padded to 4 digits (`order_items` observed range is 1-21; 4
  digits gives headroom to 9999 items per order without re-deriving the format).
- The padded encoding preserves numeric ordering lexicographically, so
  `ORDER BY source_updated_at, source_cursor_key` matches
  `ORDER BY source_updated_at, order_id, order_item_id`.
- `source_cursor_key` is a derived, deterministic, reversible encoding used only for
  cursor comparison and checkpoint storage. It is never used as a primary key anywhere;
  `(order_id, order_item_id)` remains the natural primary key in `source`, `raw_stage`,
  and `silver`.
- Any future composite-key entity documents its own padding width and separator choice in
  its own contract and extraction code comment; this ADR fixes the *pattern*
  (`parent_key || ':' || lpad(child_key, N, '0')`), not a single global constant.

### Required index

`source.order_items` requires a supporting index on
`(source_updated_at, order_id, order_item_id)` to serve the bounded cursor query
efficiently, mirroring the equivalent index for `orders`.

### Batch identity, backfills, checkpoint isolation

Unchanged from ADR-002: `batch_id` remains deterministic from source, entity, cursor
before/upper, contract version, run mode, and backfill request ID. `entity_name` in
`control.checkpoint` and `control.batch` already isolates `order_items` progress from
`orders` progress — no new column is needed. Backfills for `order_items` follow the same
bounded, separately tracked, non-advancing pattern already implemented for `orders`
(`sql/warehouse/003_phase1_1.sql`).

### Hard deletes

Unchanged from ADR-002: not captured in Phase 2A. If an `order_items` row is physically
deleted at the source, extraction has no evidence of it; this limitation is documented in
the `order_items` operational contract, same as for `orders`.

## Alternatives considered

### Unpadded concatenation (`order_id || ':' || order_item_id`)

Rejected: unpadded integers sort lexicographically wrong past single digits (`'10'` <
`'2'` as strings), which would corrupt page-boundary ordering within a single
`source_updated_at` tie.

### Store a native composite cursor column (two columns instead of one string)

Rejected for this phase: it would require widening `control.checkpoint`/`control.batch`
schema and touching every cursor-comparison call site that currently assumes a single
`cursor_key text`. The padded single-string encoding achieves identical ordering
guarantees with zero schema migration, at the cost of a documented serialization rule that
each new composite-key entity must follow.

### Per-entity bespoke cursor logic with no documented pattern

Rejected: `AGENTS.md` §4 requires deterministic, tested cursor boundary behavior; an
undocumented, one-off encoding per entity would be unauditable and untestable as a
general pattern.

## Consequences

Positive:

- `order_items` reuses the exact ADR-002 recovery and checkpoint-advance protocol with no
  schema changes to `control.*`;
- ordering correctness is a testable, explicit property of the padding width, not an
  accident of ID ranges seen so far;
- the pattern generalizes to future composite-key entities (e.g. `order_payments`'s
  `(order_id, payment_sequential)`) by stating their own padding width.

Costs and limitations:

- the padding width is a contractual constant that must be revisited (and
  contract-versioned) if `order_item_id` could ever exceed 9999 for one order — not
  expected for this dataset, but documented as a boundary;
- `source_cursor_key` has no meaning outside cursor comparison and must never be exposed
  as if it were a business key in Silver/Gold.

## Reversal and migration path

If a future entity's natural key cannot be safely encoded as a single padded string
(e.g. variable-length components), a new ADR introduces a native multi-column cursor
representation and a `control.checkpoint`/`control.batch` schema migration. Existing
`order_items` (and `orders`) checkpoint rows remain valid and unaffected.
