from __future__ import annotations

import hashlib


def compute_batch_id(
    *,
    source: str,
    entity: str,
    cursor_before: str,
    cursor_upper: str,
    contract_version: str,
    run_mode: str = "incremental",
    backfill_request_id: str = "",
) -> str:
    raw = f"{source}|{entity}|{cursor_before}|{cursor_upper}|{contract_version}|{run_mode}|{backfill_request_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def compute_quarantine_id(
    entity: str, payload_hash: str, contract_version: str, codes: list[str]
) -> str:
    raw = "|".join([entity, payload_hash, contract_version, ",".join(sorted(codes))])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
