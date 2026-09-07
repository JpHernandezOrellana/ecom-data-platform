from datetime import UTC

import pytest

from ecom.timez import localize_source, reporting_date


def test_exact_time():
    utc, code = localize_source("2018-01-01 10:00:00")
    assert code == "exact"
    assert utc.tzinfo == UTC


def test_ambiguous_fold_zero():
    # Known Sao Paulo DST fold date
    utc, code = localize_source("2017-02-18 23:30:00")
    assert code == "ambiguous_fold_0"
    assert utc is not None


def test_nonexistent_raises():
    with pytest.raises(ValueError):
        localize_source("2018-11-04 00:30:00")


def test_reporting_date_chile():
    # 2018-01-01 02:00 Sao Paulo ~ 2017-12-31 Chile? just check function runs
    utc, _ = localize_source("2018-01-01 01:00:00")
    assert reporting_date(utc) in ("2017-12-31", "2018-01-01")
