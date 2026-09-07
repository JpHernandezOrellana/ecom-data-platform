# ADR-002: Incremental cursor, batch commit, and recovery protocol

**Status:** Accepted  
**Date:** 2026-09-06  
**Owner:** Juan Pablo  
**Accepted by:** Juan Pablo  
**Accepted date:** 2026-09-06  
**Decision scope:** Phase 1  
**Related SDD:** `SDD.md`, Sections 13-15, 23-25  

## Context

Olist does not provide a uniform operational mutation timestamp. The simulator-owned source therefore adds `source_created_at` and `source_updated_at`. The bootstrap gives all historical orders one deterministic mutation timestamp, which creates many timestamp ties.

The ingestion process writes Parquet on a filesystem and checkpoint state in PostgreSQL. No transaction can atomically commit both systems. The design must prevent missed rows, avoid duplicate committed batches, and recover from interruption without claiming exactly-once delivery.

## Decision

### Cursor

Orders use the lexicographic cursor:

```text
(source_updated_at, order_id)
```

The lower bound is exclusive and the fixed upper bound is inclusive. A run reads a stable source snapshot and uses:

```sql
WHERE (source_updated_at, order_id) > (:cursor_before_timestamp, :cursor_before_order_id)
  AND (source_updated_at, order_id) <= (:cursor_upper_timestamp, :cursor_upper_order_id)
ORDER BY source_updated_at, order_id
```

An absent initial checkpoint means no lower predicate. Null cursor components fail the entity before extraction. All pages use the same source snapshot and upper bound.

Phase 1 serializes source simulation and extraction. It has no overlap window and makes no claim about concurrent polling safety.

### Logical batch identity

`batch_id` is deterministic from source, entity, cursor before, cursor upper, contract version, run mode, and backfill request ID when applicable.

Normal retries reuse the same identity. Backfill retries reuse a stable request ID. A separately authorized backfill receives a new request ID.

### Filesystem publication

Accepted Bronze rows and permitted extraction-quarantine rows are written beneath one temporary batch directory. Files are closed and checksummed, then the manifest is written last. One atomic rename on the same filesystem publishes the complete directory to a path partitioned by the UTC date of `cursor_upper` and `batch_id`.

The partition date is logical-batch state, not wall-clock attempt time, so retries use the same path.

### Checkpoint commit

After filesystem publication, one `warehouse-postgres.control` transaction:

1. verifies the stored normal checkpoint still equals `cursor_before`;
2. registers the committed manifest;
3. advances the checkpoint to `cursor_after`;
4. marks the ingestion stage successful.

The update uses compare-and-swap semantics. Backfill batches register and advance only backfill request state; they never change the normal checkpoint.

### Recovery

Before a new normal extraction, the process searches for a committed incremental manifest matching the current checkpoint but missing its completed control transaction. It verifies identity and checksums, completes the transaction, and does not re-extract or write another committed batch.

A temporary directory without a committed manifest cannot advance state. Downstream warehouse loading reads registered committed batches independently from source extraction.

## Alternatives considered

### Timestamp-only cursor

Rejected because the bootstrap deliberately contains many equal timestamps and timestamp-only progress can miss rows.

### Advance checkpoint after Gold publication

Rejected because a warehouse or dbt failure would force unnecessary source re-extraction even though durable Bronze evidence already exists.

### Store checkpoint only in files

Rejected because transactional compare-and-swap, queryable run state, and safe concurrent-commit detection are clearer in PostgreSQL.

### Claim a cross-system atomic transaction

Rejected because PostgreSQL and a local Parquet filesystem do not share one transaction manager. Deterministic recovery is the honest guarantee.

### Overlap window in Phase 1

Rejected because writes and extraction are serialized. It will be considered only with an explicit concurrent-write and bounded-lateness requirement.

## Consequences

Positive consequences:

- equal timestamps are safe;
- retries converge to one committed logical batch;
- a crash between filesystem and checkpoint commits is recoverable;
- source and downstream replay state remain separate;
- behavior can be demonstrated with failure injection.

Costs and limitations:

- manifest discovery and checksum verification are required;
- one entity has one checkpoint committer at a time;
- hard deletes are not captured;
- concurrent source writes are not supported in Phase 1;
- the protocol is at-least-once with idempotent convergence, not exactly once.

## Reversal and migration path

Concurrent polling, overlap windows, CDC, or object storage require a new ADR. Existing manifests, source-version keys, and checkpoint history should remain readable during migration.
