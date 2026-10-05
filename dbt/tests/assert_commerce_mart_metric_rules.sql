-- GOLD-COM-MONEY-001/002, GOLD-COM-AOV-001.
select reporting_date
from {{ ref('mart_daily_commerce') }}
where gmv_brl < 0
   or freight_value_brl < 0
   or gross_order_value_brl < 0
   or canceled_item_value_brl < 0
   or unavailable_item_value_brl < 0
   or eligible_order_count < 0
   or gross_order_value_brl is distinct from (gmv_brl + freight_value_brl)
   or (eligible_order_count = 0 and aov_brl is not null)
   or (
     eligible_order_count > 0
     and aov_brl is distinct from (gmv_brl / eligible_order_count)::numeric(18,2)
   )
