-- AGENTS.md 6.8 (no silent loss): an order whose customer_id is absent from stg_customers
-- must fail the build. In the full Olist dataset this never happens (customer_id is 1:1
-- with orders), but it must not pass silently if a future source change breaks that
-- invariant.
select distinct o.order_id
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c on c.customer_id = o.customer_id
where c.customer_id is null
