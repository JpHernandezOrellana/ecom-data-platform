{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- ADR-007: BRL/CLP cross-rate via USD, one row per reporting_date that mart_daily_commerce
-- actually needs (every distinct date in int_order_commerce, eligible or not -- the mart
-- reports gmv_clp=0 with full provenance even for an all-canceled date).
--
-- Each leg independently carries forward the most recent prior rate up to 7 calendar days
-- back (lower-bound inclusive window on rate_date). A date with no resolvable rate on
-- either leg within that window yields a null clp_per_brl here, which
-- assert_fx_rate_resolves_for_commerce_dates turns into a blocking build failure rather
-- than a silently missing/zero CLP figure (AGENTS.md 6.8/6.9).
--
-- fx_rate_date is the older (more carried-forward) of the two legs' resolved dates, so a
-- reader always sees the true provenance boundary; fx_rate_is_carried_forward is true
-- whenever either leg's resolved date differs from reporting_date itself.
with dates as (
  select distinct reporting_date
  from {{ ref('int_order_commerce') }}
),
brl_resolved as (
  select
    d.reporting_date,
    brl.rate_date as brl_rate_date,
    brl.cotacao_compra,
    brl.cotacao_venda
  from dates d
  left join lateral (
    select rate_date, cotacao_compra, cotacao_venda
    from {{ source('warehouse', 'raw_fx_rate_usd_brl') }}
    where rate_date <= d.reporting_date
      and rate_date >= d.reporting_date - interval '7 days'
    order by rate_date desc
    limit 1
  ) brl on true
),
clp_resolved as (
  select
    d.reporting_date,
    clp.rate_date as clp_rate_date,
    clp.dolar_observado
  from dates d
  left join lateral (
    select rate_date, dolar_observado
    from {{ source('warehouse', 'raw_fx_rate_usd_clp') }}
    where rate_date <= d.reporting_date
      and rate_date >= d.reporting_date - interval '7 days'
    order by rate_date desc
    limit 1
  ) clp on true
)
select
  d.reporting_date,
  case
    when b.brl_rate_date is not null and c.clp_rate_date is not null
    then (c.dolar_observado / ((b.cotacao_compra + b.cotacao_venda) / 2))::numeric(18,6)
  end as clp_per_brl,
  least(b.brl_rate_date, c.clp_rate_date) as fx_rate_date,
  case
    when b.brl_rate_date is not null and c.clp_rate_date is not null
    then 'bcb_ptax+sii_dolar_observado'
  end as fx_rate_source,
  case
    when b.brl_rate_date is not null and c.clp_rate_date is not null
    then (b.brl_rate_date <> d.reporting_date or c.clp_rate_date <> d.reporting_date)
  end as fx_rate_is_carried_forward
from dates d
left join brl_resolved b on b.reporting_date = d.reporting_date
left join clp_resolved c on c.reporting_date = d.reporting_date
