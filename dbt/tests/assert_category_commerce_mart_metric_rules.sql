-- GOLD-CAT-GRAIN-001, GOLD-CAT-MONEY-001.
select reporting_date, product_category_name
from {{ ref('mart_daily_category_commerce') }}
where category_gmv_brl < 0
   or category_freight_value_brl < 0
   or eligible_item_count < 0
   or product_category_name is null
   or product_category_name_english is null
