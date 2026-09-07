from ecom.batchid import compute_batch_id


def test_deterministic_and_retry_stable():
    a = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="NONE",
        cursor_upper="X|y",
        contract_version="1.0.0",
    )
    b = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="NONE",
        cursor_upper="X|y",
        contract_version="1.0.0",
    )
    assert a == b


def test_backfill_distinct():
    a = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="A",
        cursor_upper="B",
        contract_version="1.0.0",
        run_mode="backfill",
        backfill_request_id="r1",
    )
    b = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="A",
        cursor_upper="B",
        contract_version="1.0.0",
        run_mode="backfill",
        backfill_request_id="r2",
    )
    assert a != b
