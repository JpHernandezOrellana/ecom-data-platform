from __future__ import annotations

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/olist_orders.v1.yaml"
OPERATIONAL_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/operational_orders.v1.yaml"
ITEM_BOOTSTRAP_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/olist_order_items.v1.yaml"
ITEM_OPERATIONAL_CONTRACT_PATH = (
    REPOSITORY_ROOT / "contracts/source/operational_order_items.v1.yaml"
)
PAYMENT_BOOTSTRAP_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/olist_order_payments.v1.yaml"
PAYMENT_OPERATIONAL_CONTRACT_PATH = (
    REPOSITORY_ROOT / "contracts/source/operational_order_payments.v1.yaml"
)
REFUND_OPERATIONAL_CONTRACT_PATH = (
    REPOSITORY_ROOT / "contracts/source/operational_order_refunds.v1.yaml"
)
PRODUCT_BOOTSTRAP_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/olist_products.v1.yaml"
PRODUCT_OPERATIONAL_CONTRACT_PATH = (
    REPOSITORY_ROOT / "contracts/source/operational_products.v1.yaml"
)
SELLER_BOOTSTRAP_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/olist_sellers.v1.yaml"
SELLER_OPERATIONAL_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/source/operational_sellers.v1.yaml"


def load_contract(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def schema_by_name(contract: dict) -> dict[str, dict]:
    return {field["name"]: field for field in contract["schema"]}


def accepted_values(contract: dict, field_name: str) -> set[str]:
    return set(schema_by_name(contract)[field_name].get("allowed_values", []))
