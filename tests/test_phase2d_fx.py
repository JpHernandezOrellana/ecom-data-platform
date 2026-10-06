"""Phase 2D FX rate ingestion tests (ADR-007).

Unit tests exercise the BCB/SII parsing functions directly (no network, no DB).
Integration tests exercise ecom.fetch_fx_rates against the deterministic fixture
directory (tests/fixtures/fx), never the live BCB/SII endpoints -- same principle as
every other entity's synthetic fixtures.
"""

import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ecom.config import Settings
from ecom.fetch_fx_rates import BrlRate, ClpRate, parse_bcb_response, parse_sii_year

REPO = Path(__file__).resolve().parents[1]
FX_FIXTURE_DIR = REPO / "tests" / "fixtures" / "fx"


def _run(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{REPO}/.venv/bin:{env['PATH']}"
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _pg(query: str) -> str:
    import psycopg

    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn, conn.cursor() as cur:
        cur.execute(query)
        try:
            return str(cur.fetchall())
        except psycopg.ProgrammingError:
            return "ok"


# --- Unit tests: pure parsing functions, no network, no DB ---


def test_parse_bcb_response_extracts_valid_rows():
    payload = json.dumps(
        {
            "value": [
                {
                    "cotacaoCompra": 3.25,
                    "cotacaoVenda": 3.26,
                    "dataHoraCotacao": "2018-01-02 13:00:00",
                },
                {
                    "cotacaoCompra": 3.30,
                    "cotacaoVenda": 3.31,
                    "dataHoraCotacao": "2018-01-03 13:00:00",
                },
            ]
        }
    ).encode()
    rates = parse_bcb_response(payload)
    assert rates == [
        BrlRate(date(2018, 1, 2), Decimal("3.25"), Decimal("3.26")),
        BrlRate(date(2018, 1, 3), Decimal("3.30"), Decimal("3.31")),
    ]


def test_parse_bcb_response_skips_invalid_row_without_failing_whole_response():
    payload = json.dumps(
        {
            "value": [
                {
                    "cotacaoCompra": 3.25,
                    "cotacaoVenda": 3.26,
                    "dataHoraCotacao": "2018-01-02 13:00:00",
                },
                {
                    "cotacaoCompra": -1,
                    "cotacaoVenda": 3.31,
                    "dataHoraCotacao": "2018-01-03 13:00:00",
                },
                {"cotacaoCompra": 3.1},  # missing required fields
            ]
        }
    ).encode()
    rates = parse_bcb_response(payload)
    assert len(rates) == 1
    assert rates[0].rate_date == date(2018, 1, 2)


def test_parse_bcb_response_structural_failure_on_malformed_json():
    with pytest.raises(SystemExit, match="FX-BRL-STRUCT-001"):
        parse_bcb_response(b"not json")


def test_parse_bcb_response_structural_failure_on_missing_value_key():
    with pytest.raises(SystemExit, match="FX-BRL-STRUCT-001"):
        parse_bcb_response(json.dumps({"unexpected": []}).encode())


_SII_SAMPLE_HTML = """
<html><body>
<table id="table_export">
<tr><td>D&iacute;a</td><td>Ene</td><td>Feb</td><td>Mar</td><td>Abr</td><td>May</td><td>Jun</td><td>Jul</td><td>Ago</td><td>Sep</td><td>Oct</td><td>Nov</td><td>Dic</td></tr>
<tr><td>1</td><td>614,75</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
<tr><td>2</td><td>garbage</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
<tr><td>32</td><td>655,30</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
</table>
</body></html>
"""


def test_parse_sii_year_extracts_rates_and_skips_bad_cells(tmp_path):
    settings = Settings(
        source_dsn="",
        warehouse_dsn="",
        data_dir=tmp_path,
        bootstrap_loaded_at="2018-10-20T00:00:00+00:00",
        page_size=1,
    )
    rates = parse_sii_year(settings, 2018, _SII_SAMPLE_HTML.encode("latin-1"))
    assert rates == [ClpRate(date(2018, 1, 1), Decimal("614.75"))]
    # the "garbage" cell and the invalid day=32 row must be quarantined, not crash
    quarantined = list((tmp_path / "quarantine" / "fx" / "usd_clp").glob("*.json"))
    assert len(quarantined) == 1
    record = json.loads(quarantined[0].read_text())
    assert record["reason"] == "FX-CLP-CELL-001"


def test_parse_sii_year_structural_failure_without_table_export(tmp_path):
    settings = Settings(
        source_dsn="",
        warehouse_dsn="",
        data_dir=tmp_path,
        bootstrap_loaded_at="2018-10-20T00:00:00+00:00",
        page_size=1,
    )
    with pytest.raises(SystemExit, match="FX-CLP-STRUCT-001"):
        parse_sii_year(settings, 2018, b"<html><body>no table here</body></html>")


# --- CLI argument validation (no network, no DB) ---


def test_fetch_fx_rates_rejects_inverted_date_range():
    r = _run(
        "ecom.fetch_fx_rates",
        "--from-date",
        "2018-02-01",
        "--to-date",
        "2018-01-01",
        "--fixture-dir",
        str(FX_FIXTURE_DIR),
    )
    assert r.returncode != 0
    assert "must not precede" in (r.stdout + r.stderr)


def test_fetch_fx_rates_fails_closed_on_empty_range():
    """A date range with no fixture rows at all must fail, not silently succeed."""
    r = _run(
        "ecom.fetch_fx_rates",
        "--from-date",
        "2015-01-01",
        "--to-date",
        "2015-01-02",
        "--fixture-dir",
        str(FX_FIXTURE_DIR),
    )
    assert r.returncode != 0
    assert "zero usable" in (r.stdout + r.stderr)


# --- Integration: fixture-based fetch against the running warehouse ---


@pytest.mark.integration
def test_fetch_fx_rates_from_fixture_is_idempotent():
    """Reuses the exact same fixture range CI already fetched; deliberately does not
    delete afterward -- the rest of the pipeline (final dbt build) depends on these rates
    staying resolvable for mart_daily_commerce's reporting_dates (ADR-007)."""
    r1 = _run(
        "ecom.fetch_fx_rates",
        "--from-date",
        "2017-01-01",
        "--to-date",
        "2018-02-01",
        "--fixture-dir",
        str(FX_FIXTURE_DIR),
    )
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert "usd_brl_rows=2 usd_clp_rows=2" in r1.stdout

    r2 = _run(
        "ecom.fetch_fx_rates",
        "--from-date",
        "2017-01-01",
        "--to-date",
        "2018-02-01",
        "--fixture-dir",
        str(FX_FIXTURE_DIR),
    )
    assert r2.returncode == 0, r2.stdout + r2.stderr

    assert _pg("SELECT count(*) FROM raw_stage.fx_rate_usd_brl") == "[(2,)]"
    assert _pg("SELECT count(*) FROM raw_stage.fx_rate_usd_clp") == "[(2,)]"
