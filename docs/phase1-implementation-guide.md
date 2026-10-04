# Guia de Implementacion de Fase 1

**Estado documentado:** Fase 1.1 cerrada
**Base revisada:** commit `84960ed` y hardening local de Fase 1.1
**Alcance:** slice vertical de cumplimiento de ordenes
**Fuente de diseno:** `SDD.md`, ADR-001 a ADR-004, contratos y glosario de metricas

Este documento explica el estado real del codigo de Fase 1. Distingue entre el
comportamiento implementado, la evidencia de ejecucion registrada y los puntos
en que el codigo todavia no materializa completamente una regla del diseno.
No define metricas ni arquitectura nuevas.

## 1. Que problema resuelve

La Fase 1 demuestra que los datos de ordenes no necesitan ser consultados
analiticamente desde el sistema operacional. Construye un camino reproducible
desde una copia historica de Olist y cambios simulados hasta un mart Gold de
cumplimiento.

El producto publicado responde, por fecha de compra chilena, cuantas ordenes
fueron compradas, entregadas, canceladas, entregadas tarde, cuanto demoraron y
cuantas tienen problemas conocidos de calidad de cumplimiento. No es un
historial de eventos de estado ni un mart de ventas.

```text
CSV Olist -> source.orders -> extraccion incremental -> Bronze / cuarentena
                                                        |
                                                        v
                                                   raw_stage.orders
                                                        |
                                                        v
                                              silver.stg_orders (dbt)
                                                        |
                                                        v
                              gold_candidate.mart_daily_order_fulfillment__<id>
                                                        |
                                                        v
                                  gold.mart_daily_order_fulfillment (vista estable)
```

## 2. Limites y decisiones vigentes

La arquitectura usa dos servicios PostgreSQL locales con Docker Compose:

- `source-postgres` contiene el simulador operacional y `source.orders`.
- `warehouse-postgres` contiene control, raw, Silver, candidates y Gold.
- Bronze y cuarentena se guardan como Parquet local fuera de ambas bases.

Esta separacion implementa ADR-001: el warehouse no depende de consultas
analiticas contra la fuente operacional. No se introdujeron Airflow, CDC,
streaming, Spark, servicios cloud, dashboard ni acceso de agentes.

La fuente historica son las ordenes de Olist. Sus fechas sin zona horaria se
interpretan como `America/Sao_Paulo`; los instantes canonicos se guardan en UTC
y la fecha de reporte se proyecta a `America/Santiago`. Una hora ambigua usa
`fold=0`; una hora inexistente se rechaza. Esta es una suposicion documentada,
no una afirmacion sobre la zona horaria original del dataset.

## 3. Bootstrap de datos historicos

Comando: `python -m ecom.bootstrap`.

El bootstrap lee `olist_orders_dataset.csv`, exige el encabezado esperado y
valida identificadores, dominio de estados y timestamps. Las filas aceptadas se
insertan de forma idempotente en `source.orders`; las rechazadas se conservan en
`data/quarantine/bootstrap/...` antes de evaluar el umbral de rechazo.

El umbral implementado permite como maximo 10 filas rechazadas y una tasa no
mayor a 1 por ciento. Un encabezado incompatible falla el archivo completo. El
timestamp operacional de bootstrap es configurable mediante
`BOOTSTRAP_LOADED_AT`, para que los empates iniciales del cursor sean
deterministas.

Archivos principales:

- `src/ecom/bootstrap.py`
- `contracts/source/olist_orders.v1.yaml`
- `data/manifest.json`
- `sql/source/001_orders.sql`

## 4. Fuente operacional y mutaciones demostrativas

`source.orders` representa el ultimo estado operacional de una orden. Su clave
es `order_id`; `source_updated_at` es propiedad del simulador y permite capturar
inserciones y cambios posteriores.

El comando `python -m ecom.mutate` crea una orden sintetica y actualiza una
orden existente con un timestamp posterior. Asi se demuestra que una corrida
incremental captura tanto una insercion como una nueva version de una orden.

La extraccion usa el rol lector configurado por
`scripts/create_source_reader.sh`. El script es idempotente, concede solo
lectura sobre el esquema `source` y fue verificado con una lectura permitida y
un `DELETE` denegado. Bootstrap y mutaciones usan `SOURCE_DSN`, que conserva
las credenciales de escritura del simulador.

## 5. Extraccion incremental, batches y checkpoint

Comando: `python -m ecom.extract`.

El cursor es la tupla lexicografica `(source_updated_at, order_id)`. Cada
ventana tiene limite inferior exclusivo y limite superior inclusivo. La corrida
abre una transaccion `REPEATABLE READ`, fija el cursor superior al inicio y
consulta solo las columnas necesarias dentro de esa ventana.

El identificador de batch es determinista a partir de fuente, entidad, ventana,
version de contrato, modo y solicitud de backfill. Por tanto, reintentar la
misma ventana converge al mismo `batch_id`.

Cada batch se escribe primero en un directorio temporal con:

- Bronze aceptado en `bronze/accepted.parquet`.
- Cuarentena permitida en `quarantine/rejected.parquet` cuando existe.
- `manifest.json` con cursores, conteos, version contractual y checksums.

El directorio se publica con un rename atomico local. Solo despues se registra
el batch y se avanza el checkpoint en una transaccion del warehouse con
compare-and-swap. Si el proceso cae despues del rename y antes de esa
transaccion, el siguiente intento verifica el manifest existente, registra el
batch y no extrae ni crea un segundo batch.

La garantia real es procesamiento al menos una vez con convergencia idempotente;
no se afirma exactly-once entre filesystem y PostgreSQL.

Archivos principales:

- `src/ecom/extract.py`
- `src/ecom/cursor.py`
- `src/ecom/batchid.py`
- `src/ecom/db.py`
- `sql/warehouse/001_control.sql`

## 6. Cuarentena y calidad

La cuarentena evita perdida silenciosa de filas invalidas. Errores estructurales
como un encabezado incompatible o un cursor nulo detienen el flujo. Errores de
fila recuperables, como estado no permitido o identificador invalido, se
preservan con su payload, hash y codigos de violacion cuando el batch queda bajo
el umbral permitido.

Los problemas de negocio conocidos no se corrigen ni se descartan. Silver los
expone como flags: entrega sin timestamp de cliente, entrega anterior a compra,
entrega anterior a entrega al carrier y carrier anterior a aprobacion. Las
metricas Gold deciden explicitamente cuando una orden es elegible.

## 7. Carga al warehouse y Silver

Comando: `python -m ecom.load`.

El loader toma solamente batches registrados como `committed` y carga Bronze a
`raw_stage.orders`. La clave `(order_id, source_updated_at)` y `ON CONFLICT DO
NOTHING` hacen idempotente la carga canonica de una version fuente.

El modelo dbt `silver.stg_orders` selecciona una version vigente por `order_id`
con `source_updated_at desc, batch_id desc`. Tambien deriva `reporting_date` en
Chile y los flags de calidad. Su grano es una fila por orden en su version mas
reciente conocida.

## 8. Gold y publicacion certificada

El modelo dbt `mart_daily_order_fulfillment` crea una tabla candidate versionada
por `PUBLICATION_ID`. Su grano es una fila por `reporting_date`, donde la fecha
es la fecha de compra convertida a `America/Santiago`.

El candidate calcula:

- `order_count`
- `delivered_order_count`
- `canceled_order_count`
- `late_delivered_order_count`
- `late_delivery_eligible_order_count`
- `late_delivery_rate`
- `average_delivery_duration_days`
- `orders_with_fulfillment_quality_issue`

Una orden entregada cuenta como valida solo si tiene timestamp de entrega al
cliente y este no es anterior a la compra. Una entrega exactamente en la fecha
estimada no es tarde. La tasa de atrasos y la duracion promedio son nulas si no
existe denominador o conjunto elegible, respectivamente.

`python -m ecom.publish --publication-id <id> --test-results <run_results.json>
--dbt-manifest <manifest.json>` verifica que dbt construyo el candidate solicitado y
que todas sus pruebas directas pasaron. Solo entonces actualiza en una transaccion la
vista estable `gold.mart_daily_order_fulfillment` y el registro de publicacion. Una
verificacion fallida conserva la vista Gold anterior. Tambien evita dos publicaciones
simultaneas.

Las formulas canonicas estan en `docs/metrics.md`; el contrato de consumo esta
en `contracts/gold/mart_daily_order_fulfillment.v1.yaml`.

## 9. Pruebas y evidencia disponible

La evidencia de cierre en `docs/evidence/phase1-closure.md` registra un entorno
local de referencia, una corrida limpia y estas reconciliaciones:

| Capa | Conteo | Semantica |
|---|---:|---|
| `source.orders` | 99,442 | Estado operacional actual. |
| Bronze comprometido | 99,447 | Versiones aceptadas distintas. |
| `raw_stage.orders` | 99,447 | Una copia canonica por version fuente. |
| `silver.stg_orders` | 99,442 | Una version vigente por orden. |
| Gold | 99,442 | Suma de `order_count` por cohorte. |

La suite comprometida tiene pruebas de cursor, timestamps, bootstrap,
cuarentena, checksums, recuperacion de crash, compare-and-swap, carga
idempotente, backfill, publicacion, reintentos de conexion y reconciliacion.
Los modelos dbt prueban nulidad, unicidad, dominio de estados y la presencia de
anomalias conocidas.

La ultima evidencia registrada declara `28 passed`, Ruff limpio y dbt con
`PASS=7 WARN=0 ERROR=0 SKIP=0 TOTAL=7`. Los contenedores no se mantienen
encendidos como requisito del repositorio; se levantan con `docker compose up
-d` al ejecutar el runbook.

## 10. Cierre de alineacion Fase 1.1

Fase 1.1 implementa y verifica los limites que faltaban entre el codigo y los
artefactos aceptados. No cambia las metricas ni la arquitectura de Fase 1.

| Area | Estado de Fase 1.1 |
|---|---|
| Contratos y bootstrap | La validacion deriva patrones, dominios, campos requeridos, umbrales y version desde YAML. El CSV productivo debe coincidir con el hash del manifest; los fixtures requieren una opcion explicita. Duplicados de `order_id` bloquean el bootstrap. |
| Extraccion y Bronze | Un cursor servidor consume `BATCH_PAGE_SIZE` por pagina. Bronze preserva textos de timestamp y codigos de resolucion, y la validacion operacional comprueba identificadores y proveniencia. |
| Carga | Antes de marcar un batch `loaded`, el loader verifica manifest, checksums, apertura Parquet y conteo de filas. Cualquier diferencia falla cerrado. |
| Backfill | `control.backfill_request` conserva ventana, razon, estado y batch. Una solicitud nueva exige limites `(from, to]` y razon; sus reintentos reutilizan la ventana registrada sin tocar el checkpoint normal. |
| Publicacion | La promocion exige `run_results.json` y `manifest.json` de dbt para el candidate exacto, registra esas rutas y usa columnas explicitas en la vista Gold. |
| Contrato Gold | dbt prueba grano, no nulidad, limites de conteos, denominador/tasa, duracion y reconciliacion por fecha contra Silver. |
| Retencion | `python -m ecom.retention` retiene cinco candidates publicados, expira fallidos con mas de siete dias y se niega a borrar el candidate referenciado por Gold. |

La evidencia reproducible del cierre esta en `docs/evidence/phase1_1-closure.md`.

## 11. Que no existe todavia

Fase 1 no publica GMV, AOV, revenue, reembolsos, montos BRL, montos CLP ni
conversion FX. Tampoco ingiere items, pagos, clientes, productos, vendedores o
geolocalizacion. No captura hard deletes ni demuestra seguridad ante escrituras
concurrentes en la fuente.

CI basico ya existe (`.github/workflows/ci.yml`, lint + tests + dbt build sobre fixture
sintetico). Una CLI de backfill, retencion automatica de candidates, Airflow,
dashboarding, cloud y componentes distribuidos quedan fuera del slice actual.

## 12. Punto de partida para Fase 2

El siguiente paso no es agregar tablas sin definiciones. Primero se deben
aceptar las semanticas de GMV, AOV, cancelaciones y reembolsos, junto con una
fuente historica BRL a CLP y su politica para dias sin cotizacion. Luego se
deben crear contratos y pruebas para `order_items`, que es el siguiente slice
recomendado porque establece el grano de item necesario para metricas
monetarias correctas.

Los detalles de progreso y comandos reproducibles se mantienen en
`docs/evidence/progress-report.md` y `README.md`.
