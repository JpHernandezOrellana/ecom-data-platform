-- GOLD-CAT-ORPHAN-001 / AGENTS.md 6.8 (no silent loss): an order_item whose product_id is
-- absent from stg_products must fail the build, not be silently merged into the "unknown"
-- category bucket (which is reserved for a product that exists with a null category).
select distinct order_id, order_item_id
from {{ ref('int_order_items_category') }}
where product_category_name is null
