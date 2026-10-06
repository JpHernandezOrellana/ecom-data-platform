# ADR-007: BRL-to-CLP foreign exchange source and conversion policy

**Status:** Accepted (design only — implementation deferred to the CLP phase)
**Date:** 2026-10-04
**Owner:** Juan Pablo
**Accepted by:** Juan Pablo
**Accepted date:** 2026-10-04
**Decision scope:** Phase 2D (CLP reporting), design accepted now so Phase 2A/2B BRL
models are built against a known future column contract
**Related SDD:** `SDD.md`, deferred-decisions section; `docs/metrics.md`

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

## Reversal and migration path

If a direct official BRL/CLP series becomes available later, this ADR is superseded by a
new ADR that replaces the cross-rate derivation while keeping the same additive column
contract, so downstream consumers of `gmv_clp` etc. are unaffected.
