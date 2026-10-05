-- GOLD-COM-RECON-001: gmv_brl reconciles to sum(item_value) over eligible orders by cohort.
with silver_gmv as (
  select
    reporting_date,
    coalesce(sum(case when is_commerce_eligible then item_value end), 0)::numeric(18,2) as gmv_brl
  from {{ ref('int_order_commerce') }}
  group by reporting_date
), mart as (
  select reporting_date, gmv_brl
  from {{ ref('mart_daily_commerce') }}
)
select coalesce(silver_gmv.reporting_date, mart.reporting_date) as reporting_date
from silver_gmv
full outer join mart using (reporting_date)
where silver_gmv.gmv_brl is distinct from mart.gmv_brl
