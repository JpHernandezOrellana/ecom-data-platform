{{ config(schema='gold_candidate', materialized='table', alias='mart_daily_refunds__' ~ env_var('PUBLICATION_ID', 'local')) }}

-- Grain: one row per refund-date cohort (date of refunded_at, America/Santiago).
-- Entirely synthetic demo data (ADR-005); never netted into mart_daily_commerce.gmv_brl.
select
  reporting_date,
  count(*)::bigint as refund_count,
  sum(refunded_amount)::numeric(18,2) as refunded_amount_brl
from {{ ref('stg_order_refunds') }}
group by reporting_date
