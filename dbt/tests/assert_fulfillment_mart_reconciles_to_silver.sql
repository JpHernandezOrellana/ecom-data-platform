-- GOLD-ORD-RECON-001: all latest structurally accepted orders reconcile by cohort.
with silver_counts as (
  select reporting_date, count(*)::bigint as order_count
  from {{ ref('stg_orders') }}
  group by reporting_date
), mart as (
  select reporting_date, order_count
  from {{ ref('mart_daily_order_fulfillment') }}
)
select coalesce(silver_counts.reporting_date, mart.reporting_date) as reporting_date
from silver_counts
full outer join mart using (reporting_date)
where silver_counts.order_count is distinct from mart.order_count
