from __future__ import annotations

from pathlib import Path

import yaml

ALLOWED_STATUSES = {
    "created",
    "approved",
    "processing",
    "invoiced",
    "shipped",
    "delivered",
    "unavailable",
    "canceled",
}

EXPECTED_BOOTSTRAP_HEADER = [
    "order_id",
    "customer_id",
    "order_status",
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]


def load_contract(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
