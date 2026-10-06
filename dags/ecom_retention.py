"""ecom_retention: a separate, independently schedulable DAG for candidate retention.

ADR-009 deliberately kept `ecom.retention` out of `ecom_pipeline` to avoid widening that
DAG's scope. This DAG exists so retention can be triggered (manually, or later on its own
schedule) without touching `ecom_pipeline` at all -- exactly the reversal/migration path
ADR-009 anticipated.
"""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="ecom_retention",
    description="Retire old successful/failed Gold candidates (src/ecom/retention.py)",
    schedule=None,  # manually triggerable only, same posture as ecom_pipeline (ADR-009)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ecom", "housekeeping"],
) as dag:
    BashOperator(
        task_id="retention",
        bash_command="cd /opt/ecom_orders && uv run python -m ecom.retention",
    )
