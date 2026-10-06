# ADR-007: BRL-to-CLP foreign exchange source and conversion policy

**Status:** Accepted (implemented for `mart_daily_commerce.gmv_clp`; other BRL columns
and other marts remain additive follow-up work)
**Date:** 2026-10-04
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-04
**Implemented date:** 2026-10-06
**Decision scope:** Phase 2D (CLP reporting), design accepted now so Phase 2A/2B BRL
models are built against a known future column contract
**Related SDD:** `SDD.md`, deferred-decisions section; `docs/metrics.md`
**Implementation evidence:** `docs/evidence/phase2d-closure.md`

## Context

Phase 2A/2B model commerce metrics in source-currency BRL only (ADR-005). Chilean
reporting eventually needs CLP. Per the agreed sequencing, **BRL ships first, CLP later**
as an additive phase — this ADR records the FX design now, before any CLP column exists,
so BRL models are not built in a way that later blocks or reshapes CLP addition.

Neither Brazil's central bank nor Chile's publishes a direct BRL/CLP quote; both publish
rates against USD. A cross-rate must be derived, and a policy is needed for weekends,
holidays, rounding, and provenance.

## Decision

### Sources (official, free, no paid infrastructure)

- **BRL leg:** Banco Central do Brasil PTAX, daily USD/BRL `cotacaoCompra` (buy) and
  `cotacaoVenda` (sell), via the public Olinda OData API
  (`https://olinda.bcb.gov.br/olinda/servico/PTAX/...`).
- **CLP leg:** Servicio de Impuestos Internos (Chile), daily "Dólar Observado" (CLP per
  USD), published at `https://www.sii.cl/valores_y_fechas/dolar/dolar{year}.htm`.

Both are official government sources, both are free, and both require no paid
infrastructure — consistent with the project's zero-cost constraint.

### Cross-rate derivation

```text
usd_brl_rate = (cotacaoCompra + cotacaoVenda) / 2        # PTAX, per USD
usd_clp_rate = dolar_observado                           # SII, per USD (single quote)

clp_per_brl = usd_clp_rate / usd_brl_rate
```

The BRL leg uses the **average of buy and sell** PTAX quotes (not just one side) since this
is analytical reporting, not a real settled transaction; averaging is a neutral choice that
does not understate or overstate either currency's strength. The CLP leg (Dólar Observado)
already is Chile's single official reference rate, so no averaging is needed on that side.

### Rate date and missing-day policy

The conversion date is the order's `reporting_date` (purchase date in `America/Santiago`,
same cohort key as `mart_daily_commerce`), consistent with ADR-004's existing date
semantics.

If no rate is published for that exact calendar date on either leg (weekends, Chilean or
Brazilian holidays), the policy is: **carry forward the most recent prior published rate,
up to a maximum of 7 calendar days back.** If either leg has no rate within 7 days, the
row is **not silently defaulted** — it fails the FX-dependent model closed, consistent with
`AGENTS.md` §6.8 (no silent loss) and must be surfaced as a quarantined/flagged row, not a
zero or null CLP value slipped into an otherwise-complete mart.

### Rounding

Converted CLP amounts are rounded to the nearest integer using **half-up** rounding
(standard commercial rounding; Chilean peso has no subunit in practice). BRL source amounts
remain `NUMERIC(18,2)` through the conversion; only the final CLP output column is rounded
to an integer. Intermediate cross-rate arithmetic uses fixed-precision decimal, never
float, per `AGENTS.md` §6.5.

### Column contract (for the future CLP phase)

CLP columns are **additive**, never a replacement of BRL columns:

```text
gmv_brl              numeric(18,2)   -- unchanged, from ADR-005
gmv_clp              bigint          -- added only in the CLP phase
fx_rate_clp_per_brl  numeric(18,6)   -- recorded for traceability
fx_rate_date         date            -- the date the rate was actually dated from
fx_rate_source       text            -- 'bcb_ptax+sii_dolar_observado'
fx_rate_is_carried_forward boolean   -- true if the 7-day carry-forward rule applied
```

Every CLP figure is traceable to the exact rate, its date, and whether it was carried
forward — a reader must never have to guess why a CLP number does not match a naive
same-day lookup.

## Alternatives considered

### Use only one central bank's cross-rate table directly (if one existed)

Rejected: no direct official BRL/CLP series was found from either central bank; deriving
via USD cross-rate is the standard, auditable approach using two official sources.

### Use a single point-in-time quote (buy *or* sell) for PTAX instead of an average

Rejected: picking one side would silently bias every converted figure toward a
transactional stance (as if actually buying or selling currency) that does not apply to
analytical reporting.

### Default missing days to zero or to the last Phase-1-era rate indefinitely

Rejected: unbounded carry-forward could silently use a stale, materially wrong rate
indefinitely during a data gap. The 7-day cap forces an explicit failure instead of silent
staleness, per `AGENTS.md` §6.8/§6.9.

### Round at the BRL stage instead of only the final CLP output

Rejected: would compound rounding error across every intermediate aggregation; BRL stays
at its native 2-decimal precision throughout, and only the final presentation-layer CLP
value is rounded.

### Implement CLP now, alongside BRL

Rejected per explicit sequencing decision: BRL ships first and is independently useful and
testable; CLP is strictly additive and should not block or complicate the Phase 2A/2B
vertical slice.

## Consequences

Positive:

- FX design is fixed before any CLP column exists, so Phase 2A/2B BRL work cannot paint
  itself into a corner;
- every CLP figure carries full rate provenance;
- missing-rate handling fails closed rather than silently drifting.

Costs and limitations:

- requires a small ingestion job for the two public rate sources before CLP can be
  implemented (out of scope for this ADR; tracked as a Phase 2D task);
- the 7-day carry-forward cap means a sufficiently long outage in both source sites blocks
  CLP computation for affected dates until resolved — an accepted tradeoff over silent
  staleness;
- SII's published page format is HTML tables keyed by month, not a clean API; the future
  ingestion job must parse it defensively and treat unparseable pages as quarantined
  source data, not a crash.

## Implementation notes (2026-10-06)

- `ecom.fetch_fx_rates` fetches both legs for a bounded `--from-date`/`--to-date` range
  into `raw_stage.fx_rate_usd_brl`/`fx_rate_usd_clp` (direct warehouse tables, not
  simulator-owned `source.*` — these are external reference data with no operational
  cursor, just an idempotent upsert by `rate_date`).
- HTTP calls shell out to `curl` rather than Python's `urllib`, to avoid depending on a
  correctly configured local CA bundle (a real portability issue encountered during
  implementation) and to avoid adding a `requests`/`certifi` dependency for two simple GET
  calls (`AGENTS.md` §13).
- SII's per-year page actually contains one clean consolidated table
  (`id="table_export"`, one row per day, one column per month, Chilean comma-decimal),
  not the twelve per-month tables the page also renders — confirmed by inspecting the live
  page before writing the parser, not assumed from the ADR's prose.
- `--fixture-dir` makes the command read deterministic CSV fixtures instead of calling the
  live sources; CI and all automated tests use this path exclusively (no test depends on
  BCB/SII availability).
- The 7-day carry-forward and fail-closed behavior (`int_fx_cross_rate`,
  `assert_fx_rate_resolves_for_commerce_dates`) was verified by a manual reproduction, not
  an automated pytest test: no existing test in this repository invokes `dbt` from
  pytest, and introducing that pattern for one scenario was judged worse than a documented
  manual repro (see `docs/evidence/phase2d-closure.md`).
- Scope for this slice is `mart_daily_commerce.gmv_clp` only, plus its four provenance
  columns. `freight_value_clp`, `gross_order_value_clp`, `aov_clp`, and CLP on
  `mart_daily_category_commerce`/`mart_daily_refunds` are deferred additive follow-ups
  using the identical pattern — not a design gap, a scope decision to ship one complete
  vertical slice of the mechanism before widening it (`AGENTS.md` §5).
- CLP columns are independently rounded per column; this repository does not assert that
  BRL-side arithmetic identities (e.g. `gross = gmv + freight`) also hold exactly for their
  CLP counterparts, since none of those additional CLP columns exist yet.

## Reversal and migration path

If a direct official BRL/CLP series becomes available later, this ADR is superseded by a
new ADR that replaces the cross-rate derivation while keeping the same additive column
contract, so downstream consumers of `gmv_clp` etc. are unaffected.
