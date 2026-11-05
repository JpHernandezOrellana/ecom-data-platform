#!/usr/bin/env bash
# Ejecuta una demostración completa sobre fixtures sintéticos y no limpia volúmenes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  printf '%s\n' "Falta .env. Ejecuta: cp .env.example .env" >&2
  exit 1
fi

set -a
# La demo usa las credenciales locales configuradas por el operador, pero nunca
# consume el dataset real ni llama a los proveedores FX.
source .env
set +a

export DATA_DIR="$ROOT/var/demo-data"
export BATCH_PAGE_SIZE="${BATCH_PAGE_SIZE:-2}"
PUBLICATION_ID="demo_$(date -u +%Y%m%d%H%M%S)"

mkdir -p "$DATA_DIR"
docker compose up -d --wait source-postgres warehouse-postgres

uv run python -m ecom.bootstrap \
  --csv tests/fixtures/orders_small.csv \
  --attempt-id "$PUBLICATION_ID-orders" \
  --allow-unverified-input
uv run python -m ecom.bootstrap_customers \
  --csv tests/fixtures/customers_small.csv \
  --attempt-id "$PUBLICATION_ID-customers" \
  --allow-unverified-input
uv run python -m ecom.bootstrap_items \
  --csv tests/fixtures/order_items_small.csv \
  --attempt-id "$PUBLICATION_ID-items" \
  --allow-unverified-input
uv run python -m ecom.bootstrap_payments \
  --csv tests/fixtures/order_payments_small.csv \
  --attempt-id "$PUBLICATION_ID-payments" \
  --allow-unverified-input
uv run python -m ecom.bootstrap_products \
  --csv tests/fixtures/products_small.csv \
  --attempt-id "$PUBLICATION_ID-products" \
  --allow-unverified-input
uv run python -m ecom.bootstrap_sellers \
  --csv tests/fixtures/sellers_small.csv \
  --attempt-id "$PUBLICATION_ID-sellers" \
  --allow-unverified-input

scripts/create_source_reader.sh

uv run python -m ecom.extract
uv run python -m ecom.load
uv run python -m ecom.extract_customers
uv run python -m ecom.load_customers
uv run python -m ecom.extract_items
uv run python -m ecom.load_items
uv run python -m ecom.extract_payments
uv run python -m ecom.load_payments
uv run python -m ecom.extract_products
uv run python -m ecom.load_products
uv run python -m ecom.extract_sellers
uv run python -m ecom.load_sellers
uv run python -m ecom.generate_refunds --ts 2018-02-01T00:00:00+00:00
uv run python -m ecom.extract_refunds
uv run python -m ecom.load_refunds
uv run python -m ecom.fetch_fx_rates \
  --from-date 2017-01-01 \
  --to-date 2018-02-01 \
  --fixture-dir tests/fixtures/fx

(
  cd dbt
  uv run --project .. python -m dbt.cli.main seed --profiles-dir .
  PUBLICATION_ID="$PUBLICATION_ID" uv run --project .. python -m dbt.cli.main build --profiles-dir .
)

for product in \
  mart_daily_order_fulfillment \
  mart_daily_commerce \
  mart_daily_refunds \
  mart_daily_category_commerce; do
  uv run python -m ecom.publish \
    --product "$product" \
    --publication-id "$PUBLICATION_ID" \
    --test-results dbt/target/run_results.json \
    --dbt-manifest dbt/target/manifest.json
done

printf '\nDemo publicada con publication_id=%s\n' "$PUBLICATION_ID"
printf '%s\n' "Consulta las vistas gold.* en el warehouse; Airflow no es necesario para este recorrido."
