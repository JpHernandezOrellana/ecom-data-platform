{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one seller_id.
with ranked as (
  select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state,
    source_created_at,
    source_updated_at,
    batch_id,
    row_number() over (
      partition by seller_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_sellers') }}
)
select
  seller_id,
  seller_zip_code_prefix,
  seller_city,
  seller_state,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
