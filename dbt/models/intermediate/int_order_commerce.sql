{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- Grain: one row per order_id with items pre-aggregated (ADR-005), so GMV/AOV never
-- multiply the order denominator by item count. Orders with items but no matching
-- stg_orders row are excluded here (known Phase 2A limitation, documented in the
-- mart_daily_commerce contract).
with item_totals as (
  select
    order_id,
    sum(price) as item_value,
    sum(freight_value) as freight_value
  from {{ ref('stg_order_items') }}
  group by order_id
)
select
  o.order_id,
  o.order_status,
  o.reporting_date,
  item_totals.item_value,
  item_totals.freight_value,
  (o.order_status not in ('canceled', 'unavailable')) as is_commerce_eligible
from {{ ref('stg_orders') }} o
join item_totals on item_totals.order_id = o.order_id
