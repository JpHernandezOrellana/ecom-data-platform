-- GOLD-REF-RECON-001: refunded_amount_brl reconciles to sum(refunded_amount) by cohort.
with silver_totals as (
  select
    reporting_date,
    sum(refunded_amount)::numeric(18,2) as refunded_amount_brl
  from {{ ref('stg_order_refunds') }}
  group by reporting_date
), mart as (
  select reporting_date, refunded_amount_brl
  from {{ ref('mart_daily_refunds') }}
)
select coalesce(silver_totals.reporting_date, mart.reporting_date) as reporting_date
from silver_totals
full outer join mart using (reporting_date)
where silver_totals.refunded_amount_brl is distinct from mart.refunded_amount_brl
