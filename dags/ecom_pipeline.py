"""ecom_pipeline: orchestrates the already-independent extract/load/dbt/publish commands.

ADR-009. Every task is a thin BashOperator wrapper around an existing, independently
tested CLI entry point (`uv run python -m ecom.X`) -- this DAG contains no transformation
logic of its own and is not the system of record for checkpoint state (`control.*` in the
warehouse remains that; see SDD.md §30).

Does NOT orchestrate: bootstrap (one-time historical load), scripts/create_source_reader.sh
(host-side one-time setup, requires `docker compose exec` access this container does not
have), ecom.mutate/ecom.generate_refunds (demo data generators), or ecom.retention
(separate, independently schedulable concern).
"""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup

PROJECT_DIR = "/opt/ecom_orders"
RUN_CMD = f"cd {PROJECT_DIR} && uv run python -m"
PUBLICATION_ID = "airflow_{{ ts_nodash }}"

# (entity_name, extract_module, load_module)
ENTITIES = [
    ("orders", "ecom.extract", "ecom.load"),
    ("order_items", "ecom.extract_items", "ecom.load_items"),
    ("order_payments", "ecom.extract_payments", "ecom.load_payments"),
    ("order_refunds", "ecom.extract_refunds", "ecom.load_refunds"),
    ("products", "ecom.extract_products", "ecom.load_products"),
    ("sellers", "ecom.extract_sellers", "ecom.load_sellers"),
    ("customers", "ecom.extract_customers", "ecom.load_customers"),
]

# (product_name,) -- must match publish.PRODUCTS keys exactly.
GOLD_PRODUCTS = [
    "mart_daily_order_fulfillment",
    "mart_daily_commerce",
    "mart_daily_refunds",
    "mart_daily_category_commerce",
]

with DAG(
    dag_id="ecom_pipeline",
    description="Extract/load per entity -> shared dbt build -> publish every Gold product",
    schedule=None,  # manually triggerable only (docs/metrics.md freshness cadence)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ecom", "phase2"],
) as dag:
    load_tasks = []

    for entity_name, extract_module, load_module in ENTITIES:
        with TaskGroup(group_id=entity_name) as entity_group:
            extract_task = BashOperator(
                task_id=f"extract_{entity_name}",
                bash_command=f"{RUN_CMD} {extract_module}",
            )
            load_task = BashOperator(
                task_id=f"load_{entity_name}",
                bash_command=f"{RUN_CMD} {load_module}",
            )
            extract_task >> load_task
        load_tasks.append(entity_group)

    fetch_fx_rates = BashOperator(
        task_id="fetch_fx_rates",
        bash_command=(
            f"{RUN_CMD} ecom.fetch_fx_rates "
            "--from-date {{ macros.ds_add(ds, -14) }} "
            "--to-date {{ ds }}"
        ),
    )

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command=f"cd {PROJECT_DIR}/dbt && uv run --project .. dbt seed --profiles-dir .",
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {PROJECT_DIR}/dbt && PUBLICATION_ID={PUBLICATION_ID} "
            "uv run --project .. dbt build --profiles-dir ."
        ),
        trigger_rule="all_success",
    )

    [*load_tasks, fetch_fx_rates, dbt_seed] >> dbt_build

    for product in GOLD_PRODUCTS:
        BashOperator(
            task_id=f"publish_{product}",
            bash_command=(
                f"{RUN_CMD} ecom.publish --product {product} "
                f"--publication-id {PUBLICATION_ID} "
                f"--test-results {PROJECT_DIR}/dbt/target/run_results.json "
                f"--dbt-manifest {PROJECT_DIR}/dbt/target/manifest.json"
            ),
        ).set_upstream(dbt_build)
