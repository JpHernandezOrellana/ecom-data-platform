from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import Settings
from .db import connect, ensure_phase_2d_fx_warehouse_schema

BCB_PERIODO_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    "?@dataInicial='{from_mmddyyyy}'&@dataFinalCotacao='{to_mmddyyyy}'&$format=json"
)
SII_YEAR_URL = "https://www.sii.cl/valores_y_fechas/dolar/dolar{year}.htm"
MONTH_COLUMNS = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


@dataclass(frozen=True)
class BrlRate:
    rate_date: date
    cotacao_compra: Decimal
    cotacao_venda: Decimal


@dataclass(frozen=True)
class ClpRate:
    rate_date: date
    dolar_observado: Decimal


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch BRL/CLP FX reference rates for a bounded date range (ADR-007)"
    )
    p.add_argument("--from-date", required=True, help="ISO date, inclusive")
    p.add_argument("--to-date", required=True, help="ISO date, inclusive")
    p.add_argument(
        "--fixture-dir",
        default=None,
        help="Read deterministic usd_brl.csv/usd_clp.csv from this directory instead of "
        "calling the live BCB/SII sources. Required for tests and CI (no network).",
    )
    return p.parse_args()


def _curl(url: str, timeout_s: int = 20) -> bytes:
    result = subprocess.run(
        ["curl", "-sS", "-m", str(timeout_s), "-A", "Mozilla/5.0", url],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"fx fetch structural failure: curl failed for {url}: {result.stderr!r}")
    return result.stdout


def _quarantine(settings: Settings, leg: str, reason: str, detail: dict) -> None:
    qdir = settings.data_dir / "quarantine" / "fx" / leg
    qdir.mkdir(parents=True, exist_ok=True)
    record = {
        "quarantined_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "detail": detail,
    }
    fname = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}.json"
    (qdir / fname).write_text(json.dumps(record, indent=2))


def parse_bcb_response(raw: bytes) -> list[BrlRate]:
    """Parse a BCB CotacaoDolarPeriodo JSON response into BrlRate rows.

    Pure/testable without network: a malformed top-level response (not JSON, or missing
    the "value" array) is a structural failure (FX-BRL-STRUCT-001); an individual
    unparseable or non-positive row is skipped rather than failing the whole response.
    """
    try:
        payload = json.loads(raw)
        rows = payload["value"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"fx fetch structural failure (FX-BRL-STRUCT-001): {error}") from error
    rates: list[BrlRate] = []
    for row in rows:
        try:
            rate_date = datetime.fromisoformat(row["dataHoraCotacao"]).date()
            compra = Decimal(str(row["cotacaoCompra"]))
            venda = Decimal(str(row["cotacaoVenda"]))
        except (KeyError, ValueError, InvalidOperation):
            continue
        if compra <= 0 or venda <= 0:
            continue
        rates.append(BrlRate(rate_date, compra, venda))
    return rates


def _fetch_brl_rates_live(from_d: date, to_d: date) -> list[BrlRate]:
    url = BCB_PERIODO_URL.format(
        from_mmddyyyy=from_d.strftime("%m-%d-%Y"), to_mmddyyyy=to_d.strftime("%m-%d-%Y")
    )
    return parse_bcb_response(_curl(url))


_SII_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL)
_SII_ROW_RE = re.compile(r"<tr.*?</tr>", re.DOTALL)
_SII_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL)


def parse_sii_year(settings: Settings, year: int, html: bytes) -> list[ClpRate]:
    text = html.decode("latin-1")
    if 'id="table_export"' not in text:
        raise SystemExit(
            f"fx fetch structural failure (FX-CLP-STRUCT-001): year {year} missing table_export"
        )
    tables = _SII_TABLE_RE.findall(text)
    export_table = next((t for t in tables if 'id="table_export"' in t), None)
    if export_table is None:
        raise SystemExit(
            f"fx fetch structural failure (FX-CLP-STRUCT-001): year {year} table_export not parsed"
        )
    rows = _SII_ROW_RE.findall(export_table)
    if len(rows) < 2:
        raise SystemExit(
            f"fx fetch structural failure (FX-CLP-STRUCT-001): year {year} has no data rows"
        )
    rates: list[ClpRate] = []
    for row_html in rows[1:]:
        cells = [c.strip() for c in _SII_CELL_RE.findall(row_html)]
        if len(cells) != 13:
            _quarantine(settings, "usd_clp", "FX-CLP-STRUCT-001", {"year": year, "row": cells})
            continue
        try:
            day = int(cells[0])
        except ValueError:
            _quarantine(settings, "usd_clp", "FX-CLP-CELL-001", {"year": year, "row": cells})
            continue
        for month_idx, cell in enumerate(cells[1:], start=1):
            value = cell.replace("&nbsp;", "").strip()
            if not value:
                continue
            try:
                rate_date = date(year, month_idx, day)
            except ValueError:
                continue
            try:
                parsed = Decimal(value.replace(".", "").replace(",", "."))
            except InvalidOperation:
                _quarantine(
                    settings,
                    "usd_clp",
                    "FX-CLP-CELL-001",
                    {"year": year, "rate_date": rate_date.isoformat(), "raw": value},
                )
                continue
            if parsed <= 0:
                _quarantine(
                    settings,
                    "usd_clp",
                    "FX-CLP-RANGE-001",
                    {"year": year, "rate_date": rate_date.isoformat(), "raw": value},
                )
                continue
            rates.append(ClpRate(rate_date, parsed))
    return rates


def _fetch_clp_rates_live(settings: Settings, from_d: date, to_d: date) -> list[ClpRate]:
    rates: list[ClpRate] = []
    for year in range(from_d.year, to_d.year + 1):
        html = _curl(SII_YEAR_URL.format(year=year))
        rates.extend(parse_sii_year(settings, year, html))
    return [r for r in rates if from_d <= r.rate_date <= to_d]


def _read_brl_fixture(path: Path) -> list[BrlRate]:
    rates: list[BrlRate] = []
    with path.open(newline="") as h:
        for row in csv.DictReader(h):
            rates.append(
                BrlRate(
                    date.fromisoformat(row["rate_date"]),
                    Decimal(row["cotacao_compra"]),
                    Decimal(row["cotacao_venda"]),
                )
            )
    return rates


def _read_clp_fixture(path: Path) -> list[ClpRate]:
    rates: list[ClpRate] = []
    with path.open(newline="") as h:
        for row in csv.DictReader(h):
            rates.append(
                ClpRate(date.fromisoformat(row["rate_date"]), Decimal(row["dolar_observado"]))
            )
    return rates


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env()
    from_d = date.fromisoformat(args.from_date)
    to_d = date.fromisoformat(args.to_date)
    if to_d < from_d:
        raise SystemExit("--to-date must not precede --from-date")

    if args.fixture_dir:
        fixture_dir = Path(args.fixture_dir)
        brl_rates = [
            r
            for r in _read_brl_fixture(fixture_dir / "usd_brl.csv")
            if from_d <= r.rate_date <= to_d
        ]
        clp_rates = [
            r
            for r in _read_clp_fixture(fixture_dir / "usd_clp.csv")
            if from_d <= r.rate_date <= to_d
        ]
    else:
        brl_rates = [
            r for r in _fetch_brl_rates_live(from_d, to_d) if from_d <= r.rate_date <= to_d
        ]
        clp_rates = _fetch_clp_rates_live(settings, from_d, to_d)

    if not brl_rates:
        raise SystemExit(
            "fx fetch structural failure: zero usable BRL-leg rates for requested range"
        )
    if not clp_rates:
        raise SystemExit(
            "fx fetch structural failure: zero usable CLP-leg rates for requested range"
        )

    retrieved_at = datetime.now(UTC)
    with connect(settings.warehouse_dsn) as conn, conn.cursor() as cur:
        ensure_phase_2d_fx_warehouse_schema(conn)
        for r in brl_rates:
            cur.execute(
                """INSERT INTO raw_stage.fx_rate_usd_brl (rate_date, cotacao_compra, cotacao_venda, retrieved_at)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (rate_date) DO UPDATE SET
                     cotacao_compra=EXCLUDED.cotacao_compra, cotacao_venda=EXCLUDED.cotacao_venda,
                     retrieved_at=EXCLUDED.retrieved_at""",
                (r.rate_date, r.cotacao_compra, r.cotacao_venda, retrieved_at),
            )
        for r in clp_rates:
            cur.execute(
                """INSERT INTO raw_stage.fx_rate_usd_clp (rate_date, dolar_observado, retrieved_at)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (rate_date) DO UPDATE SET
                     dolar_observado=EXCLUDED.dolar_observado, retrieved_at=EXCLUDED.retrieved_at""",
                (r.rate_date, r.dolar_observado, retrieved_at),
            )
        conn.commit()
    print(f"fx fetch ok: usd_brl_rows={len(brl_rates)} usd_clp_rows={len(clp_rates)}")


if __name__ == "__main__":
    main()
