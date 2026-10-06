-- GOLD-COM-CLP-001/002 (ADR-007): gmv_clp is non-negative, rate provenance is complete
-- whenever gmv_clp is present, and gmv_clp is exactly the independently-rounded
-- conversion of gmv_brl (never recomputed differently downstream).
select reporting_date
from {{ ref('mart_daily_commerce') }}
where gmv_clp < 0
   or fx_rate_clp_per_brl <= 0
   or fx_rate_date is null
   or fx_rate_source is distinct from 'bcb_ptax+sii_dolar_observado'
   or gmv_clp is distinct from round(gmv_brl * fx_rate_clp_per_brl)::bigint
