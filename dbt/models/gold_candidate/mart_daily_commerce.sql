{{ config(schema='gold_candidate', materialized='table', alias='mart_daily_commerce__' ~ env_var('PUBLICATION_ID', 'local')) }}

-- Grain: one row per reporting_date (Chilean purchase-date cohort), matching
-- mart_daily_order_fulfillment. Metrics per ADR-005: GMV excludes freight and
-- excludes canceled/unavailable orders; AOV denominator counts distinct eligible
-- orders, never item rows.
--
-- CLP columns (ADR-007, Phase 2D) are additive: gmv_clp is gmv_brl independently rounded
-- (half-up, via Postgres round()) through the resolved cross-rate, with full rate
-- provenance. int_fx_cross_rate guarantees a non-null clp_per_brl for every
-- reporting_date reachable from int_order_commerce once assert_fx_rate_resolves_for_
-- commerce_dates passes; this model does not re-implement that fail-closed check.
with commerce as (
  select
    reporting_date,
    count(distinct case when is_commerce_eligible then order_id end)::bigint as eligible_order_count,
    coalesce(sum(case when is_commerce_eligible then item_value end), 0)::numeric(18,2) as gmv_brl,
    coalesce(sum(case when is_commerce_eligible then freight_value end), 0)::numeric(18,2) as freight_value_brl,
    (
      coalesce(sum(case when is_commerce_eligible then item_value end), 0)
      + coalesce(sum(case when is_commerce_eligible then freight_value end), 0)
    )::numeric(18,2) as gross_order_value_brl,
    case
      when count(distinct case when is_commerce_eligible then order_id end) = 0 then null
      else (
        coalesce(sum(case when is_commerce_eligible then item_value end), 0)
        / count(distinct case when is_commerce_eligible then order_id end)
      )
    end::numeric(18,2) as aov_brl,
    coalesce(sum(case when order_status = 'canceled' then item_value end), 0)::numeric(18,2) as canceled_item_value_brl,
    coalesce(sum(case when order_status = 'unavailable' then item_value end), 0)::numeric(18,2) as unavailable_item_value_brl
  from {{ ref('int_order_commerce') }}
  group by reporting_date
)
select
  commerce.reporting_date,
  commerce.eligible_order_count,
  commerce.gmv_brl,
  commerce.freight_value_brl,
  commerce.gross_order_value_brl,
  commerce.aov_brl,
  commerce.canceled_item_value_brl,
  commerce.unavailable_item_value_brl,
  round(commerce.gmv_brl * fx.clp_per_brl)::bigint as gmv_clp,
  fx.clp_per_brl as fx_rate_clp_per_brl,
  fx.fx_rate_date,
  fx.fx_rate_source,
  fx.fx_rate_is_carried_forward
from commerce
left join {{ ref('int_fx_cross_rate') }} fx on fx.reporting_date = commerce.reporting_date
