from datetime import UTC, datetime

from ecom.cursor import Cursor, build_predicate, cursor_after


def test_lower_exclusive_upper_inclusive_sql():
    sql = build_predicate(True)
    assert "(source_updated_at, order_id) >" in sql
    assert "<=" in sql
    assert "ORDER BY source_updated_at, order_id" in sql


def test_initial_has_no_lower():
    sql = build_predicate(False)
    assert "before" not in sql
    assert "<=" in sql


def test_cursor_after_equals_upper():
    upper = Cursor(datetime(2018, 10, 20, tzinfo=UTC), "zz")
    rows = [Cursor(datetime(2018, 10, 19, tzinfo=UTC), "aa")]
    assert cursor_after(rows, upper) == upper
    assert cursor_after([], upper) is None
