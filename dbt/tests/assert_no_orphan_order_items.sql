-- GOLD-COM-ORPHAN-001 / AGENTS.md 6.8 (no silent loss): an order_item whose order_id is
-- absent from stg_orders must fail the build, not silently disappear from
-- int_order_commerce via the inner join.
select distinct i.order_id
from {{ ref('stg_order_items') }} i
left join {{ ref('stg_orders') }} o on o.order_id = i.order_id
where o.order_id is null
