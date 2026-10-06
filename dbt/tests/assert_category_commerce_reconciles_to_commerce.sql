-- GOLD-CAT-RECON-001: sum(category_gmv_brl) by reporting_date equals mart_daily_commerce.gmv_brl.
with category_totals as (
  select reporting_date, sum(category_gmv_brl)::numeric(18,2) as gmv_brl
  from {{ ref('mart_daily_category_commerce') }}
  group by reporting_date
), commerce as (
  select reporting_date, gmv_brl
  from {{ ref('mart_daily_commerce') }}
)
select coalesce(category_totals.reporting_date, commerce.reporting_date) as reporting_date
from category_totals
full outer join commerce using (reporting_date)
where category_totals.gmv_brl is distinct from commerce.gmv_brl
