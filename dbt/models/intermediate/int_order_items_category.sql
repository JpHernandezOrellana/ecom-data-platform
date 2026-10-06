{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- Grain: one row per order_item, carrying its product's category (ADR-008). Unlike
-- int_order_commerce (pre-aggregated to order grain), category attribution is per item
-- because one order can span multiple categories.
--
-- The join to stg_products is left, not inner: a product_id absent from stg_products
-- (orphan) must fail the build via assert_no_orphan_order_item_products, not be silently
-- excluded here. A product that exists with a null category is already coalesced to the
-- literal "unknown" by stg_products, so a null product_category_name reaching this model
-- always means a true orphan, never a legitimate missing category.
select
  oi.order_id,
  oi.order_item_id,
  oi.product_id,
  oi.seller_id,
  oi.price,
  oi.freight_value,
  o.order_status,
  o.reporting_date,
  (o.order_status not in ('canceled', 'unavailable')) as is_commerce_eligible,
  p.product_category_name,
  coalesce(t.product_category_name_english, 'unknown') as product_category_name_english,
  s.seller_id as resolved_seller_id
from {{ ref('stg_order_items') }} oi
join {{ ref('stg_orders') }} o on o.order_id = oi.order_id
left join {{ ref('stg_products') }} p on p.product_id = oi.product_id
left join {{ ref('stg_sellers') }} s on s.seller_id = oi.seller_id
left join {{ ref('product_category_name_translation') }} t
  on t.product_category_name = p.product_category_name
