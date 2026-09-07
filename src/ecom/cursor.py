from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, order=True)
class Cursor:
    updated_at: datetime
    key: str


def build_predicate(has_lower: bool) -> str:
    if has_lower:
        return (
            "WHERE (source_updated_at, order_id) > (%(before_ts)s, %(before_key)s) "
            "AND (source_updated_at, order_id) <= (%(upper_ts)s, %(upper_key)s) "
            "ORDER BY source_updated_at, order_id"
        )
    return (
        "WHERE (source_updated_at, order_id) <= (%(upper_ts)s, %(upper_key)s) "
        "ORDER BY source_updated_at, order_id"
    )


def cursor_after(rows: list[Cursor], upper: Cursor) -> Cursor | None:
    """After fully accounting a non-empty window, cursor_after == fixed upper."""
    if not rows:
        return None
    return upper
