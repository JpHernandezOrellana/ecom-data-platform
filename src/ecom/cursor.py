from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, order=True)
class Cursor:
    updated_at: datetime
    key: str


def build_predicate(has_lower: bool, key_column: str = "order_id") -> str:
    """Build the bounded cursor predicate for one natural or derived key column.

    ``key_column`` defaults to ``order_id`` (ADR-002). Composite-key entities pass their
    derived ``source_cursor_key`` column instead (ADR-006); the comparison semantics
    (lower-exclusive, upper-inclusive, lexicographic) are identical either way.
    """
    if has_lower:
        return (
            f"WHERE (source_updated_at, {key_column}) > (%(before_ts)s, %(before_key)s) "
            f"AND (source_updated_at, {key_column}) <= (%(upper_ts)s, %(upper_key)s) "
            f"ORDER BY source_updated_at, {key_column}"
        )
    return (
        f"WHERE (source_updated_at, {key_column}) <= (%(upper_ts)s, %(upper_key)s) "
        f"ORDER BY source_updated_at, {key_column}"
    )


def cursor_after(rows: list[Cursor], upper: Cursor) -> Cursor | None:
    """After fully accounting a non-empty window, cursor_after == fixed upper."""
    if not rows:
        return None
    return upper
