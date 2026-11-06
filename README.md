# Plataforma de Datos para E-commerce

Plataforma local de ingeniería de datos que transforma cambios de un sistema operacional
de comercio electrónico en productos analíticos confiables.

El proyecto ingiere pedidos, ítems, pagos, productos, vendedores y clientes desde
PostgreSQL; conserva evidencia original en Parquet; valida contratos y filas inválidas;
modela métricas con dbt; y publica vistas Gold certificadas para análisis de
cumplimiento, comercio y categorías.

No intenta ser un sistema transaccional, una plataforma de alertas ni una demostración
de infraestructura distribuida. Su objetivo es demostrar cómo construir una frontera
reproducible entre una fuente operacional y datos analíticos versionados.

## Problema

Un sistema operacional de pedidos no debería ser al mismo tiempo el almacén de
analítica. Este proyecto separa ambas responsabilidades y permite responder preguntas
como:

- ¿Cuántos pedidos se compraron y entregaron por fecha?
- ¿Qué proporción de pedidos válidos llegó tarde?
- ¿Cuál es el GMV y el flete por cohorte de compra?
- ¿Cómo se distribuye el comercio por categoría de producto?
- ¿Qué observaciones de pagos o devoluciones requieren revisión?

El producto principal es una familia de productos Gold, no solo una tabla final:

| Producto | Grano | Uso principal |
|---|---|---|
| `mart_daily_order_fulfillment` | Una fila por fecha de compra | Cumplimiento y entregas tardías |
| `mart_daily_commerce` | Una fila por fecha de compra | GMV, flete, AOV y CLP |
| `mart_daily_category_commerce` | Fecha y categoría | Desglose del GMV por producto |
| `mart_daily_refunds` | Una fila por fecha de devolución | Eventos sintéticos de devolución |

`gmv_brl` no es ingreso contable: excluye flete, pedidos cancelados/no disponibles y devoluciones.
Las devoluciones son sintéticas porque Olist no contiene eventos observados de devolución.
`gmv_clp` es una conversión aditiva y actualmente es la única métrica CLP certificada.
Las definiciones completas están en el [glosario de métricas](docs/metrics.md).

## Cómo funciona

```mermaid
flowchart LR
    A[Fuente operacional PostgreSQL] --> B[Extracción incremental]
    B --> C[Contrato y validación]
    C --> D[Bronze Parquet]
    C --> E[Cuarentena Parquet]
    D --> F[Almacén PostgreSQL]
    F --> G[dbt Silver e intermedios]
    G --> H[Candidato Gold]
    H --> I[Pruebas y reconciliaciones]
    I --> J[Vistas Gold certificadas]
```

Cada entidad usa una ventana incremental acotada por cursor. La extracción fija su
límite superior dentro de un snapshot estable y registra un lote comprometido antes
de avanzar el punto de control.

El flujo conserva tres estados que cumplen funciones distintas:

- **Bronze:** evidencia de lo recibido, con manifest y hashes.
- **Silver:** versiones normalizadas y selección del estado actual por clave.
- **Gold:** productos de consumo con grano, métricas y pruebas explícitas.

Una publicación Gold se construye primero como candidato. Solo una ejecución dbt
exitosa y validada puede reemplazar la vista estable. Un fallo de transformación no
debe reemplazar la última publicación certificada.

## Demo de portafolio

La ruta más corta usa fixtures sintéticos, no requiere descargar Olist, no consulta
proveedores FX y no inicia Airflow:

```bash
cp -n .env.example .env
uv sync --frozen --extra dev
scripts/demo_synthetic.sh
```

La demo:

- Levanta los dos PostgreSQL locales.
- Ingresa las siete entidades.
- Ejecuta extracción incremental y carga idempotente.
- Genera una devolución sintética.
- Usa tasas de cambio sintéticas para BRL/CLP.
- Ejecuta `dbt seed` y `dbt build`.
- Publica los cuatro productos Gold.

El script utiliza `var/demo-data/`, ignorado por Git, y no elimina volúmenes Docker.
Para una demostración reproducible desde cero, usa un proyecto Compose nuevo o reinicia
los volúmenes de forma explícita. El `publication_id` se imprime al finalizar.

La demo separa el procesamiento del consumo: los productos quedan consultables como
vistas `gold.*` en el almacén. No hay un panel residente en esta versión.

## Arquitectura de datos

### Ingesta y recuperación

- Carga inicial determinista con suma de comprobación para el dataset Olist.
- Extracción incremental por `(source_updated_at, key)`.
- Paginación con ventana superior fija.
- Reprocesamientos acotados que no avanzan el punto de control normal.
- Reintentos seguros e idempotencia por lote.

### Calidad de datos

- Contratos explícitos para entradas operacionales y productos Gold.
- Filas inválidas aisladas en cuarentena cuando es seguro continuar.
- Cambios estructurales incompatibles fallan cerrados.
- Comprobaciones de huérfanos, reconciliaciones, grano y métricas.
- Tipos monetarios de precisión fija y política temporal documentada.

### Publicación analítica

- Candidatos Gold con identificador de publicación.
- Artefactos `manifest.json` y `run_results.json` asociados a la misma invocación dbt.
- Bloqueo transaccional por producto y por punto de control.
- Vistas Gold estables independientes de las tablas candidatas.
- Retención segura de candidatos antiguos y fallidos.

## Decisiones técnicas

- **PostgreSQL operacional y almacén:** separa extracción de consultas analíticas y
  permite demostrar cargas, puntos de control y restricciones relacionales sin servicios pagos.
- **Python y Parquet:** el volumen de la demo no justifica un framework distribuido; los
  archivos comprometidos permiten conservar evidencia y reanudar después de una caída.
- **dbt:** concentra transformaciones, documentación, pruebas y contratos de los productos
  de consumo.
- **Candidato Gold → vista certificada:** evita que una corrida fallida exponga resultados
  parciales o mezcle generaciones de datos.
- **Airflow opcional:** agenda los mismos comandos existentes, pero no contiene la lógica
  de negocio. El flujo manual sigue funcionando sin un planificador residente.
- **Sin Spark, Kafka ni nube:** no se agregan componentes distribuidos sin una necesidad
  de volumen, latencia o disponibilidad que lo justifique.

## Empezar

El dataset histórico de Olist no está incluido en Git. Está sujeto a sus propios términos
CC BY-NC-SA 4.0 y debe ubicarse en `dataset/` respetando los nombres originales.

Para el flujo completo se necesita Docker Desktop, Python 3.12, `uv` y un `.env` local:

```bash
cp -n .env.example .env
uv sync --frozen --extra dev
docker compose up -d --wait source-postgres warehouse-postgres
```

El procedimiento detallado para la carga inicial, el lector, la extracción, dbt y la
publicación está en la [guía operativa](docs/phase1-implementation-guide.md). La demo sintética es el
recorrido recomendado para una primera revisión.

Airflow es opcional y se activa separadamente:

```bash
docker compose --profile airflow up -d airflow
```

Su DAG es manual y local: no se declara una frecuencia recurrente sin un requisito de
actualización definido. La configuración está en [Airflow](dags/ecom_pipeline.py) y la
decisión arquitectónica en [ADR-009](docs/adrs/ADR-009-airflow-orchestration.md).

## Verificaciones

La integración continua ejecuta análisis estático, pruebas unitarias y un ciclo sintético completo con dos PostgreSQL
efímeros. La verificación local de cierre V1 incluyó:

- 25 pruebas unitarias aprobadas.
- 49 pruebas de integración aprobadas.
- Reconciliación final aprobada.
- dbt en las etapas base y final con `67/67` nodos exitosos.
- Publicación de los cuatro productos Gold en ambas etapas.
- Demo sintética completa con fixtures y sin red externa.

Estos resultados corresponden a fixtures sintéticos. El procesamiento del dataset Olist
completo requiere sus archivos locales y se valida por separado; no se debe inferir su
resultado a partir de la demo pequeña.

## Alcance deliberado

Esta versión no incluye:

- Dashboard o API pública.
- CDC, streaming o captura de hard deletes.
- Infraestructura en la nube o alta disponibilidad.
- Métricas de clientes nuevos/recurrentes.
- Métricas Gold por vendedor.
- GMV neto de devoluciones.
- CLP para columnas y productos todavía no certificados.

Estas omisiones son decisiones de alcance, no componentes incompletos ocultos. El estado
actual, invariantes y próximas etapas están registrados en
[`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).

## Documentación

- [Estado actual](docs/CURRENT_STATE.md): alcance, evidencia y pendientes.
- [Glosario de métricas](docs/metrics.md): grano y definiciones de negocio.
- [SDD](SDD.md): diseño técnico aceptado.
- [ADR-002](docs/adrs/ADR-002-incremental-commit-protocol.md): cursor, lote, punto de control y recuperación.
- [ADR-003](docs/adrs/ADR-003-contract-quality-quarantine.md): contratos y cuarentena.
- [ADR-004](docs/adrs/ADR-004-fulfillment-mart.md): Gold y promoción certificada.
- [ADR-005](docs/adrs/ADR-005-commerce-metrics.md): GMV, AOV, flete y devoluciones.
- [Pruebas](docs/testing/phase1-test-matrix.md): cobertura y casos de fallo.
- [Evidencia histórica](docs/evidence/): cierres de fases anteriores.

## Licencia y fuentes

El código se distribuye bajo [MIT](LICENSE). El dataset Olist conserva sus propios
términos y no se incluye en este repositorio. Las credenciales y configuraciones locales
se mantienen fuera de Git.
