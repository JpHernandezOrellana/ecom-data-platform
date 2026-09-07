from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SOURCE_TZ = ZoneInfo("America/Sao_Paulo")
REPORT_TZ = ZoneInfo("America/Santiago")
_UTC = timezone.utc

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def localize_source(text: str | None) -> tuple[datetime | None, str | None]:
    """Localize naive Olist text as America/Sao_Paulo, fold=0 if ambiguous.

    Returns (utc_dt, resolution_code). Raises ValueError if nonexistent/unparseable.
    None input -> (None, None).
    """
    if text is None or text == "":
        return None, None
    try:
        naive = datetime.strptime(text.strip(), TIMESTAMP_FORMAT)  # noqa: DTZ007 - source timestamps are timezone-naive by contract
    except ValueError as e:
        raise ValueError(f"unparseable timestamp: {text!r}") from e
    # Detect nonexistent/ambiguous via round-trip check using fold 0/1
    dt0 = naive.replace(tzinfo=SOURCE_TZ, fold=0)
    dt1 = naive.replace(tzinfo=SOURCE_TZ, fold=1)
    try:
        _ = dt0.utcoffset()
        _ = dt1.utcoffset()
    except Exception as e:
        raise ValueError(f"nonlocalizable timestamp: {text!r}") from e
    # Nonexistent times in zoneinfo do not raise; detect via gap heuristic:
    # convert to UTC and back; if local wall time shifts, treat fold properly.
    # Simplest deterministic rule per SDD: if offsets differ -> ambiguous -> fold=0.
    # Nonexistent detection: both folds map to same UTC but back-conversion differs.
    # We approximate with dateutil-free check: use utcoffset transitions is complex;
    # rely on explicit known behavior: raise only if conversion round-trip fails.
    off0 = dt0.utcoffset()
    off1 = dt1.utcoffset()
    utc0 = dt0.astimezone(_UTC)
    utc1 = dt1.astimezone(_UTC)
    back0 = utc0.astimezone(SOURCE_TZ).replace(tzinfo=None)
    back1 = utc1.astimezone(SOURCE_TZ).replace(tzinfo=None)
    if off0 == off1:
        if back0 != naive:
            raise ValueError(f"nonexistent local timestamp: {text!r}")
        return utc0, "exact"
    # Offsets differ: ambiguous (both round-trip) or nonexistent (neither round-trips)
    if back0 == naive and back1 == naive:
        return utc0, "ambiguous_fold_0"
    raise ValueError(f"nonexistent local timestamp: {text!r}")


def reporting_date(purchase_utc: datetime) -> str:
    """Chilean local date (ISO) for a UTC purchase instant."""
    if purchase_utc.tzinfo is None:
        purchase_utc = purchase_utc.replace(tzinfo=_UTC)
    return purchase_utc.astimezone(REPORT_TZ).date().isoformat()


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)
