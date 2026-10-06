# Phase 2D Closure Evidence (gmv_clp slice)

**Status:** Closed
**Closed on:** 2026-10-06
**Scope:** Implements ADR-007's BRL->CLP design for `mart_daily_commerce.gmv_clp` only.
`freight_value_clp`, `gross_order_value_clp`, `aov_clp`, and CLP on
`mart_daily_category_commerce`/`mart_daily_refunds` are explicitly deferred additive
follow-ups (same pattern, not a design gap) — this slice ships one complete vertical
mechanism (fetch -> cross-rate -> fail-closed -> certified column) rather than widening
breadth first (`AGENTS.md` §5). The live-fetch-vs-fixture strategy was confirmed with the
project owner before implementation.

## Closed scope

- `contracts/source/fx_rate_usd_brl.v1.yaml`, `fx_rate_usd_clp.v1.yaml`: external
  reference-data boundary contracts (BCB PTAX, SII Dolar Observado). These are not
  simulator-owned operational entities — no `source.*` table, no ADR-002 cursor; a rate
  for a date is immutable reference data, idempotently upserted by `rate_date`.
- `sql/warehouse/010_fx_rates.sql`: `raw_stage.fx_rate_usd_brl`/`fx_rate_usd_clp`.
- `src/ecom/fetch_fx_rates.py`: `--from-date`/`--to-date` bounded fetch. Live mode shells
  out to `curl` (not Python `urllib`, to avoid a local-CA-bundle dependency and avoid
  adding a `requests`/`certifi` dependency, `AGENTS.md` §13) for BCB's
  `CotacaoDolarPeriodo` JSON endpoint and SII's per-year HTML page. `--fixture-dir` reads
  deterministic CSV fixtures instead — required for every automated test and CI, never
  the live sources.
- SII page structure was inspected live before writing the parser: the per-year page
  contains one clean consolidated table (`id="table_export"`, header `Día, Ene..Dic`, one
  row per day 1-31, Chilean comma-decimal, `&nbsp;` for no-rate days), not the twelve
  per-month tables the same page also renders. The parser targets only that table.
- dbt: `silver.int_fx_cross_rate` (BRL/CLP cross-rate via USD, 7-day carry-forward per
  leg, independently), `assert_fx_rate_resolves_for_commerce_dates` (blocking: a
  `reporting_date` with no resolvable rate on either leg fails the build, never publishes
  a null/zero `gmv_clp`), `assert_commerce_mart_clp_rules` (non-negative, rate
  provenance complete, `gmv_clp` exactly equals `round(gmv_brl * fx_rate_clp_per_brl)`).
- `mart_daily_commerce` gains `gmv_clp`, `fx_rate_clp_per_brl`, `fx_rate_date`,
  `fx_rate_source`, `fx_rate_is_carried_forward` — additive, contract bumped to
  `1.1.0` (backward-compatible per its own compatibility policy: new columns are not a
  breaking change).
- `src/ecom/publish.py`'s `mart_daily_commerce` column tuple updated to include the new
  columns in the `CREATE OR REPLACE VIEW` projection.
- Unit tests (`tests/test_phase2d_fx.py`): BCB JSON parsing (valid rows, skipped invalid
  rows, structural failure on malformed/missing-key response), SII HTML parsing (valid
  rows, quarantined bad cells, structural failure without `table_export`), CLI date-range
  validation, CLI fail-closed on an empty resolvable range.
- Integration test: fixture-based fetch is idempotent (double-run does not duplicate
  rows).

## A real bug found and fixed during this slice's own verification

The first version of the idempotency integration test deleted **all** rows from
`raw_stage.fx_rate_usd_brl`/`fx_rate_usd_clp` in a `finally` cleanup block after running.
Running the full CI sequence locally end-to-end (not just the new test in isolation)
caught this immediately: the final dbt build failed
`assert_fx_rate_resolves_for_commerce_dates` because the integration test had wiped out
the exact rates the rest of the pipeline depended on for `mart_daily_commerce`'s
`2017-02-18`/`2018-01-01` cohorts. Fixed by removing the cleanup entirely — the fetch is
upsert-idempotent by design, so there is nothing to clean up, and the test must not
assume it owns the whole table.

## Verification

The local Docker source and warehouse services were healthy on a fresh volume. The
completed verification, following the exact CI command sequence plus the two added FX
steps, produced:

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 45 files already formatted
uv run --extra dev pytest -m "not integration" tests/     26 passed

uv run python -m ecom.bootstrap --csv tests/fixtures/orders_small.csv ...
uv run python -m ecom.bootstrap_customers --csv tests/fixtures/customers_small.csv ...
uv run python -m ecom.extract / ecom.load
uv run python -m ecom.extract_customers / ecom.load_customers
uv run python -m ecom.fetch_fx_rates --from-date 2017-01-01 --to-date 2018-02-01 \
  --fixture-dir tests/fixtures/fx
fx fetch ok: usd_brl_rows=2 usd_clp_rows=2
dbt seed                                          PASS=1 (71 rows)

PUBLICATION_ID=ci_baseline dbt build               PASS=67 WARN=0 ERROR=0 SKIP=0 TOTAL=67
publish all four products (baseline)

uv run --extra dev pytest -m integration -k "not test_reconciliation_across_layers" tests/
46 passed

uv run python -m ecom.load
PUBLICATION_ID=ci_final dbt build                  PASS=67 WARN=0 ERROR=0 SKIP=0 TOTAL=67
publish all four products (final)

uv run --extra dev pytest tests/test_integration.py::test_reconciliation_across_layers
1 passed

uv run python -m ecom.retention                    candidate retention complete
uv run --extra dev pytest -m "not integration" tests/     26 passed
```

### `gmv_clp` worked example (fixture data, final build)

The FX fixture deliberately covers business days near, but not exactly on, the two
cohort dates (both fall on a weekend/holiday with no published rate), to exercise
carry-forward naturally rather than contrive it:

```text
usd_brl.csv: 2017-02-17 (Fri) compra=3.1000 venda=3.1100; 2017-12-29 (Fri) compra=3.3100 venda=3.3200
usd_clp.csv: 2017-02-17 dolar_observado=655.30;            2017-12-29 dolar_observado=615.20

gold.mart_daily_commerce:
  reporting_date  gmv_brl  gmv_clp  fx_rate_clp_per_brl  fx_rate_date  carried_forward
  2017-02-18 (Sat) 50.00   10552    211.046699           2017-02-17    true
  2018-01-01 (Mon,   100.00  18558    185.580694           2017-12-29    true
             holiday)
```

Manual check for 2018-01-01: `clp_per_brl = 615.20 / ((3.31+3.32)/2) = 615.20/3.315 =
185.5807...`; `gmv_clp = round(100.00 * 185.580694) = round(18558.0694) = 18558`. Matches
exactly. `fx_rate_is_carried_forward = true` for both cohorts, correctly reflecting that
neither leg published a same-day rate.

### Manual fail-closed/recovery reproduction

No existing test in this repository invokes `dbt` from pytest (every other dbt-build
verification in this repo is a manual/CI step, not a pytest assertion); introducing that
pattern for one scenario was judged a worse precedent than a documented manual
reproduction. With the base pipeline built and published, a synthetic order
(`reporting_date = 2020-06-15`, far outside the fixture's rate coverage and beyond the
7-day carry-forward window) was inserted directly into `raw_stage.orders`/
`raw_stage.order_items`:

```text
$ dbt build --select stg_orders stg_order_items ... int_fx_cross_rate \
    assert_fx_rate_resolves_for_commerce_dates mart_daily_commerce
Failure in test assert_fx_rate_resolves_for_commerce_dates
  Got 1 result, configured to fail if != 0
model.ecom_orders.mart_daily_commerce .................... [SKIP]
```

`mart_daily_commerce` was correctly skipped by dbt (a failed upstream test blocks
downstream model execution in `dbt build`), confirming no null/zero `gmv_clp` could have
been silently published for that date. After deleting the synthetic rows:

```text
$ dbt build --select ... (same selection)
test.ecom_orders.assert_fx_rate_resolves_for_commerce_dates .............. [PASS]
model.ecom_orders.mart_daily_commerce ..................................... [OK]
```

The pipeline recovered cleanly with no manual intervention beyond removing the bad data,
confirming the fail-closed behavior is both correctly triggered and correctly reversible.

## Known limitations (carried forward, non-blocking)

- `freight_value_clp`, `gross_order_value_clp`, `aov_clp` do not exist yet.
- `mart_daily_category_commerce` and `mart_daily_refunds` have no CLP columns yet.
- The live BCB/SII fetch path is not exercised by any automated test; only
  `--fixture-dir` is. A maintainer running `ecom.fetch_fx_rates` live should expect SII's
  HTML structure to be the single most likely future breakage point (ADR-007's own
  documented cost).
- CLP figures are independently rounded per column; BRL-side arithmetic identities are
  not asserted to hold for CLP once more than one CLP column exists.
- No automated test directly exercises the 7-day carry-forward boundary or the
  fail-closed/recovery behavior; see the manual reproduction above instead.
