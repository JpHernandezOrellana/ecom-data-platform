{{ config(schema='gold_candidate', materialized='table', alias='mart_daily_category_commerce__' ~ env_var('PUBLICATION_ID', 'local')) }}

-- Grain: one row per (reporting_date, product_category_name), at item grain (ADR-008).
-- Eligibility and exclusion rules are identical to ADR-005, reapplied per item instead of
-- per order. sum(category_gmv_brl) by reporting_date must equal mart_daily_commerce.gmv_brl
-- for the same date (GOLD-CAT-RECON-001).
select
  reporting_date,
  product_category_name,
  product_category_name_english,
  count(*) filter (where is_commerce_eligible)::bigint as eligible_item_count,
  coalesce(sum(case when is_commerce_eligible then price end), 0)::numeric(18,2) as category_gmv_brl,
  coalesce(sum(case when is_commerce_eligible then freight_value end), 0)::numeric(18,2) as category_freight_value_brl
from {{ ref('int_order_items_category') }}
group by reporting_date, product_category_name, product_category_name_english
