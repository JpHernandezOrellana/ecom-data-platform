{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one refund_id. Entirely synthetic
-- demo data (ADR-005) -- never claimed as observed Olist history.
with ranked as (
  select
    refund_id,
    order_id,
    payment_sequential,
    refunded_amount,
    refund_reason,
    refunded_at,
    source_created_at,
    source_updated_at,
    batch_id,
    (refunded_at at time zone 'America/Santiago')::date as reporting_date,
    row_number() over (
      partition by refund_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_order_refunds') }}
)
select
  refund_id,
  order_id,
  payment_sequential,
  refunded_amount,
  refund_reason,
  refunded_at,
  reporting_date,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
