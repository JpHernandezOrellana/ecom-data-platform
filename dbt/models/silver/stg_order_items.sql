{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one (order_id, order_item_id).
with ranked as (
  select
    order_id,
    order_item_id,
    product_id,
    seller_id,
    shipping_limit_at,
    price,
    freight_value,
    source_created_at,
    source_updated_at,
    batch_id,
    row_number() over (
      partition by order_id, order_item_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_order_items') }}
)
select
  order_id,
  order_item_id,
  product_id,
  seller_id,
  shipping_limit_at,
  price,
  freight_value,
  source_created_at,
  source_updated_at,
  batch_id
from ranked
where rn = 1
