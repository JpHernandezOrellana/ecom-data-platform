-- Symmetric to assert_no_orphan_order_item_products (ADR-008): an order_item whose
-- seller_id is absent from stg_sellers must fail the build. No Gold metric is currently
-- grained by seller; this is forward-looking evidence hygiene (AGENTS.md 6.8).
select distinct order_id, order_item_id
from {{ ref('int_order_items_category') }}
where resolved_seller_id is null
