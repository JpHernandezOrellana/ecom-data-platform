-- A refund must never exceed the payment it references (generator-enforced invariant,
-- re-checked here as a defense-in-depth blocking rule, per ADR-005).
select r.refund_id
from {{ ref('stg_order_refunds') }} r
join {{ ref('stg_order_payments') }} p
  on p.order_id = r.order_id and p.payment_sequential = r.payment_sequential
where r.refunded_amount > p.payment_value
