"""Unit tests for commit-protocol helpers (no database required)."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ecom.batchid import compute_batch_id
from ecom.config import Settings
from ecom.extract import _try_recover, _verify_manifest_files


def _settings(tmp_path) -> Settings:
    return Settings(
        source_dsn="postgresql://nobody:nobody@localhost:5499/none",
        warehouse_dsn="postgresql://nobody:nobody@localhost:5499/none",
        data_dir=tmp_path / "data",
        bootstrap_loaded_at="2018-10-20T00:00:00+00:00",
        page_size=5000,
    )


def test_tmp_directory_cannot_advance_checkpoint(tmp_path):
    """COMMIT-003: recovery only scans committed paths, never tmp staging."""
    s = _settings(tmp_path)
    base = s.data_dir / "committed_batches_tmp" / "orphan"
    (base / "bronze").mkdir(parents=True, exist_ok=True)
    assert _try_recover(s, None, None) is None


def test_manifest_checksum_mismatch_fails(tmp_path):
    """COMMIT-005: tampered committed files fail verification."""
    base = tmp_path / "batch"
    (base / "bronze").mkdir(parents=True)
    pq.write_table(pa.table({"a": [1, 2]}), base / "bronze" / "accepted.parquet")
    import hashlib

    digest = hashlib.sha256((base / "bronze" / "accepted.parquet").read_bytes()).hexdigest()
    manifest = {"files": {"bronze/accepted.parquet": digest}}
    _verify_manifest_files(base, manifest)
    (base / "bronze" / "accepted.parquet").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        _verify_manifest_files(base, manifest)


def test_batch_id_stable_across_wall_clock(tmp_path):
    """COMMIT-001/002: batch identity depends on the cursor window, not time."""
    a = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="NONE",
        cursor_upper="2018-01-01T00:00:00+00:00|zz",
        contract_version="1.0.0",
    )
    b = compute_batch_id(
        source="s",
        entity="orders",
        cursor_before="NONE",
        cursor_upper="2018-01-01T00:00:00+00:00|zz",
        contract_version="1.0.0",
    )
    assert a == b
    assert json.dumps({"batch_id": a})  # manifest-serializable
