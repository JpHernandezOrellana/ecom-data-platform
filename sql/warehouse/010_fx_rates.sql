-- External FX reference rates (Phase 2D, ADR-007). Unlike operational entities, these are
-- not simulator-owned: they are pulled directly from two public government sources into
-- the warehouse by ecom.fetch_fx_rates, with no source-side table and no ADR-002
-- cursor/checkpoint (a rate for a given date is immutable reference data, not a mutating
-- operational fact; idempotent upsert by rate_date is sufficient).
CREATE SCHEMA IF NOT EXISTS raw_stage;

CREATE TABLE IF NOT EXISTS raw_stage.fx_rate_usd_brl (
  rate_date date PRIMARY KEY,
  cotacao_compra numeric(18,6) NOT NULL,
  cotacao_venda numeric(18,6) NOT NULL,
  retrieved_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_stage.fx_rate_usd_clp (
  rate_date date PRIMARY KEY,
  dolar_observado numeric(18,6) NOT NULL,
  retrieved_at timestamptz NOT NULL
);
