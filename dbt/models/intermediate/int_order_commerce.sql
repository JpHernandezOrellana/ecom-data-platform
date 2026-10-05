{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- Grain: one row per order_id with items pre-aggregated (ADR-005), so GMV/AOV never
-- multiply the order denominator by item count. The inner join would silently exclude
-- an order_item whose order_id is absent from stg_orders; assert_no_orphan_order_items
-- (GOLD-COM-ORPHAN-001) fails the build instead, so that case is never silent.
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
