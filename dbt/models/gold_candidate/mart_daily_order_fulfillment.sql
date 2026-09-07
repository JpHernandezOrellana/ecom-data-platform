{{ config(schema='gold_candidate', materialized='table', alias='mart_daily_order_fulfillment__' ~ env_var('PUBLICATION_ID', 'local')) }}

-- Grain: one row per reporting_date (Chilean purchase-date cohort).
with eligible as (
  select
    reporting_date,
    order_id,
    order_status,
    order_purchase_at,
    order_delivered_customer_at,
    order_estimated_delivery_at,
    has_fulfillment_quality_issue,
    (
      order_status = 'delivered'
      and order_delivered_customer_at is not null
      and order_delivered_customer_at >= order_purchase_at
    ) as is_delivered_valid
  from {{ ref('stg_orders') }}
)
select
  reporting_date,
  count(distinct order_id)::bigint as order_count,
  count(distinct case when is_delivered_valid then order_id end)::bigint as delivered_order_count,
  count(distinct case when order_status = 'canceled' then order_id end)::bigint as canceled_order_count,
  count(distinct case when is_delivered_valid and order_estimated_delivery_at is not null
    and order_delivered_customer_at > order_estimated_delivery_at then order_id end)::bigint as late_delivered_order_count,
  count(distinct case when is_delivered_valid and order_estimated_delivery_at is not null then order_id end)::bigint as late_delivery_eligible_order_count,
  case
    when count(distinct case when is_delivered_valid and order_estimated_delivery_at is not null then order_id end) = 0 then null
    else (count(distinct case when is_delivered_valid and order_estimated_delivery_at is not null
      and order_delivered_customer_at > order_estimated_delivery_at then order_id end)::numeric
      / count(distinct case when is_delivered_valid and order_estimated_delivery_at is not null then order_id end)::numeric)
  end as late_delivery_rate,
  avg(case when is_delivered_valid
    then extract(epoch from (order_delivered_customer_at - order_purchase_at)) / 86400.0 end)::numeric(18,6) as average_delivery_duration_days,
  count(distinct case when has_fulfillment_quality_issue then order_id end)::bigint as orders_with_fulfillment_quality_issue
from eligible
group by reporting_date
