# Thin layer on the official Airflow image: adds uv so DAG tasks can run
# `uv run python -m ecom.X` against the project checkout mounted at /opt/ecom_orders,
# using the exact same dependency set as every other entry point (ADR-009).
FROM apache/airflow:2.10.3-python3.12

USER airflow
RUN pip install --no-cache-dir uv==0.9.*

ENV UV_PROJECT_ENVIRONMENT=/home/airflow/.ecom_venv
