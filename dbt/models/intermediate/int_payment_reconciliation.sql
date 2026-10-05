{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- Diagnostic only (ADR-005): payment_value does not reconcile with price+freight_value
-- for a known fraction of orders (partial/installment payments, timing). This model
-- surfaces the mismatch for inspection; it is never used as a GMV/AOV input and is not
-- gated by a blocking dbt test, since disagreement is expected, documented behavior.
with payment_totals as (
  select
    order_id,
    sum(payment_value) as total_payment_value_brl,
    count(*) as payment_count
  from {{ ref('stg_order_payments') }}
  group by order_id
)
select
  commerce.order_id,
  commerce.reporting_date,
  (commerce.item_value + commerce.freight_value) as item_plus_freight_brl,
  payment_totals.total_payment_value_brl,
  payment_totals.payment_count,
  (payment_totals.total_payment_value_brl - (commerce.item_value + commerce.freight_value))
    as payment_item_diff_brl,
  (payment_totals.total_payment_value_brl = (commerce.item_value + commerce.freight_value))
    as payments_reconcile_with_items
from {{ ref('int_order_commerce') }} commerce
left join payment_totals on payment_totals.order_id = commerce.order_id
