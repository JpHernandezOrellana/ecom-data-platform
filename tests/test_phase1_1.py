import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ecom.contracts import OPERATIONAL_CONTRACT_PATH, load_contract
from ecom.extract import _validate_operational_row
from ecom.load import _read_committed_bronze
from ecom.publish import _verify_dbt_candidate


def _operational_row() -> dict:
    return {
        "order_id": "a" * 32,
        "customer_id": "b" * 32,
        "order_status": "created",
        "order_purchase_at": "2018-01-01T00:00:00+00:00",
        "order_purchase_at_source_text": "2017-12-31 22:00:00",
        "order_purchase_at_timezone_resolution": "exact",
        "order_approved_at": None,
        "order_approved_at_source_text": None,
        "order_approved_at_timezone_resolution": None,
        "order_delivered_carrier_at": None,
        "order_delivered_carrier_at_source_text": None,
        "order_delivered_carrier_at_timezone_resolution": None,
        "order_delivered_customer_at": None,
        "order_delivered_customer_at_source_text": None,
        "order_delivered_customer_at_timezone_resolution": None,
        "order_estimated_delivery_at": "2018-01-10T00:00:00+00:00",
        "order_estimated_delivery_at_source_text": "2018-01-09 22:00:00",
        "order_estimated_delivery_at_timezone_resolution": "exact",
        "source_created_at": "2018-01-01T00:00:00+00:00",
        "source_updated_at": "2018-01-01T00:00:00+00:00",
    }


def test_operational_contract_validates_customer_and_timestamp_provenance():
    row = _operational_row()
    assert _validate_operational_row(row, load_contract(OPERATIONAL_CONTRACT_PATH)) == []
    row["customer_id"] = "not-an-olist-id"
    row["order_purchase_at_source_text"] = None
    assert _validate_operational_row(row, load_contract(OPERATIONAL_CONTRACT_PATH)) == [
        "OP-ORD-KEY-001",
        "OP-ORD-PROV-001",
        "OP-ORD-REQUIRED-001",
    ]


def test_loader_rejects_manifest_count_mismatch(tmp_path):
    base = tmp_path / "batch"
    bronze = base / "bronze"
    bronze.mkdir(parents=True)
    file_path = bronze / "accepted.parquet"
    pq.write_table(pa.table({"order_id": ["a", "b"]}), file_path)
    manifest = {
        "accepted_count": 1,
        "files": {
            "bronze/accepted.parquet": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        },
    }
    with pytest.raises(SystemExit, match="row count mismatch"):
        _read_committed_bronze(base, manifest, "test-batch")


def _write_dbt_artifacts(base: Path, test_status: str = "pass") -> tuple[Path, Path]:
    model_id = "model.ecom_orders.mart_daily_order_fulfillment"
    test_id = "test.ecom_orders.assert_fulfillment_mart_metric_rules"
    manifest = {
        "nodes": {
            model_id: {
                "resource_type": "model",
                "name": "mart_daily_order_fulfillment",
                "relation_name": "ecom_warehouse.gold_candidate.mart_daily_order_fulfillment__phase1_1",
            },
            test_id: {
                "resource_type": "test",
                "depends_on": {"nodes": [model_id]},
            },
        }
    }
    results = {
        "results": [
            {"unique_id": model_id, "status": "success"},
            {"unique_id": test_id, "status": test_status},
        ]
    }
    manifest_path = base / "manifest.json"
    results_path = base / "run_results.json"
    manifest_path.write_text(json.dumps(manifest))
    results_path.write_text(json.dumps(results))
    return results_path, manifest_path


def test_publication_requires_passing_artifacts_for_the_requested_candidate(tmp_path):
    results_path, manifest_path = _write_dbt_artifacts(tmp_path)
    _verify_dbt_candidate("mart_daily_order_fulfillment", "phase1_1", results_path, manifest_path)


def test_publication_rejects_failed_candidate_test(tmp_path):
    results_path, manifest_path = _write_dbt_artifacts(tmp_path, test_status="fail")
    with pytest.raises(ValueError, match="tests did not pass"):
        _verify_dbt_candidate(
            "mart_daily_order_fulfillment", "phase1_1", results_path, manifest_path
        )
