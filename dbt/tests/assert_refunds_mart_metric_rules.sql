-- GOLD-REF-COUNT-001.
select reporting_date
from {{ ref('mart_daily_refunds') }}
where refund_count < 0
   or refunded_amount_brl < 0
