-- GOLD-ORD-COUNT-001/002, GOLD-ORD-LATE-001/002, GOLD-ORD-DURATION-001.
with mart as (
  select
    reporting_date,
    order_count,
    delivered_order_count,
    canceled_order_count,
    late_delivered_order_count,
    late_delivery_eligible_order_count,
    late_delivery_rate,
    average_delivery_duration_days,
    orders_with_fulfillment_quality_issue
  from {{ ref('mart_daily_order_fulfillment') }}
), expected as (
  select
    reporting_date,
    count(*) filter (
      where order_status = 'delivered'
        and order_delivered_customer_at is not null
        and order_delivered_customer_at >= order_purchase_at
    ) as valid_delivered_order_count
  from {{ ref('stg_orders') }}
  group by reporting_date
)
select mart.reporting_date
from mart
join expected using (reporting_date)
where order_count < 0
   or delivered_order_count < 0
   or canceled_order_count < 0
   or late_delivered_order_count < 0
   or late_delivery_eligible_order_count < 0
   or orders_with_fulfillment_quality_issue < 0
   or delivered_order_count > order_count
   or canceled_order_count > order_count
   or orders_with_fulfillment_quality_issue > order_count
   or late_delivered_order_count > late_delivery_eligible_order_count
   or (late_delivery_eligible_order_count = 0 and late_delivery_rate is not null)
   or (
     late_delivery_eligible_order_count > 0
     and late_delivery_rate is distinct from (
       late_delivered_order_count::numeric / late_delivery_eligible_order_count::numeric
     )
   )
   or (valid_delivered_order_count = 0 and average_delivery_duration_days is not null)
   or (valid_delivered_order_count > 0 and average_delivery_duration_days < 0)
