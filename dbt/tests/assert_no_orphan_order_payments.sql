-- GOLD-COM-ORPHAN-002 / AGENTS.md 6.8 (no silent loss): a payment whose order_id is
-- absent from stg_orders must fail the build, not disappear unnoticed. This checks
-- against stg_orders directly (not int_order_commerce), since an order can legitimately
-- have payments without ever having items (documented Olist characteristic, not an
-- integrity violation) -- that case must stay visible, not be conflated with a true
-- orphan reference to a nonexistent order.
select distinct p.order_id
from {{ ref('stg_order_payments') }} p
left join {{ ref('stg_orders') }} o on o.order_id = p.order_id
where o.order_id is null
