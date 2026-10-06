{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one product_id. A null
-- product_category_name is a known source characteristic (610 rows, ADR-008), not
-- quarantined; it is bucketed downstream as the literal category "unknown".
with ranked as (
  select
    product_id,
    product_category_name,
    product_weight_g,
    product_length_cm,
    product_height_cm,
    product_width_cm,
    source_created_at,
    source_updated_at,
    batch_id,
    row_number() over (
      partition by product_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_products') }}
)
select
  product_id,
  coalesce(product_category_name, 'unknown') as product_category_name,
  product_weight_g,
  product_length_cm,
  product_height_cm,
  product_width_cm,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
