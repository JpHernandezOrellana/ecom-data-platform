{{ config(schema='silver', materialized='table', contract={'enforced': False}) }}

-- One row per latest deterministic source version of one order_id.
with ranked as (
  select
    order_id,
    customer_id,
    order_status,
    order_purchase_at,
    order_approved_at,
    order_delivered_carrier_at,
    order_delivered_customer_at,
    order_estimated_delivery_at,
    source_created_at,
    source_updated_at,
    batch_id,
    (order_purchase_at at time zone 'America/Santiago')::date as reporting_date,
    (order_status = 'delivered' and order_delivered_customer_at is null) as fq_delivered_without_ts,
    (order_delivered_customer_at is not null and order_delivered_customer_at < order_purchase_at) as fq_delivery_before_purchase,
    (order_delivered_customer_at is not null and order_delivered_carrier_at is not null
      and order_delivered_customer_at < order_delivered_carrier_at) as fq_delivery_before_carrier,
    (order_delivered_carrier_at is not null and order_approved_at is not null
      and order_delivered_carrier_at < order_approved_at) as fq_carrier_before_approval,
    row_number() over (
      partition by order_id order by source_updated_at desc, batch_id desc
    ) as rn
  from {{ source('warehouse', 'raw_orders') }}
)
select
  order_id,
  customer_id,
  order_status,
  order_purchase_at,
  order_approved_at,
  order_delivered_carrier_at,
  order_delivered_customer_at,
  order_estimated_delivery_at,
  source_created_at,
  source_updated_at,
  batch_id,
  reporting_date,
  fq_delivered_without_ts,
  fq_delivery_before_purchase,
  fq_delivery_before_carrier,
  fq_carrier_before_approval,
  (fq_delivered_without_ts or fq_delivery_before_purchase or fq_delivery_before_carrier or fq_carrier_before_approval) as has_fulfillment_quality_issue
from ranked
where rn = 1
