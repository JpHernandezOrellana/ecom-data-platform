-- DQ-006/DQ-007: known Olist fulfillment anomalies must remain visible.
-- This test fails only if every quality flag disappears (silent correction).
select 1 as anomalies_missing
where (select count(*) from {{ ref('stg_orders') }} where has_fulfillment_quality_issue) = 0
