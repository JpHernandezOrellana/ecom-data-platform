{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one (order_id, payment_sequential).
with ranked as (
  select
    order_id,
    payment_sequential,
    payment_type,
    payment_installments,
    payment_value,
    source_created_at,
    source_updated_at,
    batch_id,
    row_number() over (
      partition by order_id, payment_sequential order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_order_payments') }}
)
select
  order_id,
  payment_sequential,
  payment_type,
  payment_installments,
  payment_value,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
