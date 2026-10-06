# Airflow Orchestration Closure Evidence (ADR-009)

**Status:** Closed
**Closed on:** 2026-10-06
**Scope:** One Airflow DAG (`ecom_pipeline`) orchestrating the already-independent
extract/load commands for all seven entities, `fetch_fx_rates`, the shared `dbt seed`/
`dbt build`, and all four `publish_*` targets. Per `SDD.md` §33, this is listed as
"Airflow after tasks work independently" — not one of the lettered Phase 2 data slices
(2A-2D), but the orchestration capability `SDD.md` §30 explicitly gates on multiple
stable stages existing, which is now true.

## Closed scope

- `docs/adrs/ADR-009-airflow-orchestration.md`: justification, scope (what is and is not
  orchestrated), local topology, and alternatives considered, per `AGENTS.md` §3's
  requirement for an explicit design reason before introducing a new orchestrator.
- `docker/airflow/Dockerfile`: thin layer on `apache/airflow:2.10.3-python3.12` adding
  `uv`, so DAG tasks run `uv run python -m ecom.X` against the same project checkout
  every other entry point uses.
- `compose.yaml`: new `airflow` service (`SequentialExecutor`, SQLite metadata DB,
  `airflow standalone`), joining the existing network, reaching
  `source-postgres`/`warehouse-postgres` by service name on the internal port 5432.
- `dags/ecom_pipeline.py`: `extract_<entity> >> load_<entity>` per entity (parallel
  across entities) plus `fetch_fx_rates`, all feeding one shared `dbt_seed`+`dbt_build`
  (`trigger_rule=all_success` — one failed entity blocks the shared build rather than
  publishing from partially stale data), fanning out to four independent `publish_*`
  tasks. `schedule=None` (manually triggerable only, matching this project's existing
  freshness posture).
- A real pre-existing gap fixed as part of this work: `dbt/profiles.yml` hardcoded
  `host: localhost` and never read `WAREHOUSE_DSN`. Fixed via a new `WAREHOUSE_HOST` env
  var (default `localhost`, so every existing host-side/CI caller is unaffected); the
  `airflow` service sets it to the container-network hostname.

## Verification

The local Docker stack (`source-postgres`, `warehouse-postgres`, `airflow`) was built and
started fresh. Orders, customers, order_items, order_payments, products, and sellers
fixtures were bootstrapped (order_refunds has none, by design — purely generated), and
the source-reader role was created, exactly as the existing manual runbooks require
before running any extraction.

```text
docker compose build airflow                      Image marcos-airflow Built
docker compose up -d --wait source-postgres warehouse-postgres
<bootstrap orders/customers/items/payments/products/sellers; create_source_reader.sh>
docker compose up -d airflow

airflow dags list-import-errors                    No data found
airflow dags list                                   ecom_pipeline | ... | is_paused=True
airflow dags unpause ecom_pipeline
airflow dags trigger ecom_pipeline
```

### First run: a real, correctly-surfaced failure

```text
dbt_seed  FAILED
  Database Error: connection to server at "localhost" ... port 5434 failed: Connection refused
```

This was the `profiles.yml`/`WAREHOUSE_HOST` gap described above, not an orchestration
bug — every extract/load task (which uses `WAREHOUSE_DSN`, already container-network
correct) had already succeeded; only the dbt invocation (which uses `profiles.yml`'s
discrete, host-hardcoded vars) failed. Fixed by adding the `WAREHOUSE_HOST` env var to
`profiles.yml` and the `airflow` Compose service, then rebuilt/recreated the container.

### Second run: full success

```text
orders.extract_orders                  success
orders.load_orders                     success
order_items.extract_order_items        success
order_items.load_order_items           success
order_payments.extract_order_payments  success
order_payments.load_order_payments     success
order_refunds.extract_order_refunds    success
order_refunds.load_order_refunds       success
products.extract_products              success
products.load_products                 success
sellers.extract_sellers                success
sellers.load_sellers                   success
customers.extract_customers            success
customers.load_customers               success
fetch_fx_rates                         success
dbt_seed                               success
dbt_build                              failed   <- see below, expected and correct
publish_*  (all four)                  upstream_failed
```

`dbt_build` failed for a second, **expected and correct** reason unrelated to
orchestration: the DAG's default `fetch_fx_rates` window is `ds-14` to `ds` (a realistic
production "recent rates" window), but the demo fixtures' orders are purchased in
2017/2018. `assert_fx_rate_resolves_for_commerce_dates` correctly failed the build closed
(ADR-007) rather than publishing an unresolved `gmv_clp`. This is the same fail-closed
mechanism verified manually in `docs/evidence/phase2d-closure.md`, now additionally
confirmed to propagate correctly through Airflow's `trigger_rule=all_success`: all four
`publish_*` tasks were correctly marked `upstream_failed` and never ran.

To complete the demonstration against the historical fixture dates (not a DAG change —
this mirrors supplying the right `--from-date`/`--to-date` for the data under test), the
FX fixture range was fetched directly against the same shared warehouse:

```bash
uv run python -m ecom.fetch_fx_rates --from-date 2017-01-01 --to-date 2018-02-01 \
  --fixture-dir tests/fixtures/fx
```

then the blocked tasks were cleared and re-ran via the Airflow CLI
(`airflow tasks clear -y ecom_pipeline -t 'dbt_build|publish_...'`):

```text
dbt_build                              success
publish_mart_daily_order_fulfillment   success
publish_mart_daily_commerce            success
publish_mart_daily_refunds             success
publish_mart_daily_category_commerce   success
```

### Published output, queried directly

```text
gold.mart_daily_order_fulfillment:
  2017-02-18  order_count=1  ...
  2018-01-01  order_count=2  delivered=1  canceled=1  ...
gold.mart_daily_commerce:
  2017-02-18  gmv_brl=50.00   gmv_clp=10552
  2018-01-01  gmv_brl=100.00  gmv_clp=18558

control.publication:
  airflow_20261006T182228 | mart_daily_category_commerce | published
  airflow_20261006T182228 | mart_daily_refunds            | published
  airflow_20261006T182228 | mart_daily_commerce           | published
  airflow_20261006T182228 | mart_daily_order_fulfillment  | published
```

All four Gold products were published under one shared `PUBLICATION_ID` generated by the
DAG's Jinja templating (`airflow_{{ ts_nodash }}`), matching the exact `gmv_clp` values
already verified by hand in the Phase 2D closure evidence.

### Unrelated regression check

```text
uv run --extra dev ruff check src tests          All checks passed!
uv run --extra dev ruff format --check src tests 45 files already formatted
uv run --extra dev pytest -m "not integration" tests/     26 passed
```

No `src/ecom/*` or `dbt/models/*` file changed in this slice besides `dbt/profiles.yml`'s
one-line fix; the DAG and Docker infrastructure are entirely new, additive files.

## `ecom_retention` (separate DAG, added 2026-10-06)

Per ADR-009's own reversal/migration path, `ecom.retention` was deliberately kept out of
`ecom_pipeline`. It is now orchestrated as its own `dags/ecom_retention.py` — one
`BashOperator` task, `schedule=None` (same manual-trigger posture as `ecom_pipeline`) —
rather than folded into the main DAG. Verified the same way: built a fresh Docker stack,
published one Gold candidate (`mart_daily_order_fulfillment`, publication `ret2`) so
retention had a real successful candidate to act on, started `airflow`, confirmed both
DAGs parse with zero import errors (`airflow dags list-import-errors` -> `No data
found`), then:

```text
airflow dags unpause ecom_retention
airflow dags trigger ecom_retention
airflow dags state ecom_retention <run_id>   ->  success
```

No changes to `ecom_pipeline` were needed to add this — confirming the separation ADR-009
anticipated actually holds in practice, not just in the design document.

## Known limitations (carried forward, non-blocking)

- Neither DAG is exercised by `.github/workflows/ci.yml`; CI continues to run the
  individual commands directly. Adding Airflow to CI is a separate, explicitly
  out-of-scope decision given the added runtime/complexity cost (ADR-009).
- `SequentialExecutor`/SQLite is Airflow's own documented local/dev configuration, not a
  claim of production operational maturity.
- `ecom_retention` runs on `schedule=None` (manual trigger only); enabling a recurring
  cadence (e.g. daily) is a one-line change deferred until there is a concrete freshness
  requirement to test against, not enabled speculatively.
- The webserver's gunicorn workers produce noisy provider-import warnings on restart;
  harmless, but not investigated further since DAG verification does not depend on the
  web UI.
