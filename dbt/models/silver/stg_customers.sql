{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one customer_id. customer_id
-- identifies the order-associated customer row; customer_unique_id represents the
-- repeat-customer identity (SDD §9.4). This slice exposes both columns and defines no
-- new-vs-returning-customer metric (deferred, SDD §37, ADR-008 "Deferred").
with ranked as (
  select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    customer_city,
    customer_state,
    source_created_at,
    source_updated_at,
    batch_id,
    row_number() over (
      partition by customer_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_customers') }}
)
select
  customer_id,
  customer_unique_id,
  customer_zip_code_prefix,
  customer_city,
  customer_state,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
