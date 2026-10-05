{{ config(schema='gold_candidate', materialized='table', alias='mart_daily_commerce__' ~ env_var('PUBLICATION_ID', 'local')) }}

-- Grain: one row per reporting_date (Chilean purchase-date cohort), matching
-- mart_daily_order_fulfillment. Metrics per ADR-005: GMV excludes freight and
-- excludes canceled/unavailable orders; AOV denominator counts distinct eligible
-- orders, never item rows.
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
