-- ADR-007 fail-closed policy: every reporting_date that mart_daily_commerce needs must
-- resolve a cross-rate within the 7-day carry-forward window on both legs. A date that
-- cannot resolve must fail the build, not silently publish a null/zero CLP figure
-- (AGENTS.md 6.8/6.9).
select reporting_date
from {{ ref('int_fx_cross_rate') }}
where clp_per_brl is null
