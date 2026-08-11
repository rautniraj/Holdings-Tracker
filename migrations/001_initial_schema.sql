-- Holdings Tracker — initial schema (Step 2a)

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE sync_runs (
  id              BIGSERIAL PRIMARY KEY,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  status          TEXT NOT NULL DEFAULT 'running',
  trade_from      DATE,
  trade_to        DATE,
  trades_fetched  INTEGER DEFAULT 0,
  trades_inserted INTEGER DEFAULT 0,
  trades_skipped  INTEGER DEFAULT 0,
  error_message   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_sync_runs_updated_at
  BEFORE UPDATE ON sync_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE dhan_trades (
  id                           BIGSERIAL PRIMARY KEY,
  order_id                     TEXT NOT NULL,
  exchange_time                TIMESTAMPTZ NOT NULL,
  transaction_type             TEXT NOT NULL,
  traded_quantity              INTEGER NOT NULL,
  traded_price                 NUMERIC(18, 4) NOT NULL,
  security_id                  TEXT NOT NULL,
  dhan_client_id               TEXT,
  exchange_order_id            TEXT,
  exchange_trade_id            TEXT,
  exchange_segment             TEXT,
  product_type                 TEXT,
  order_type                   TEXT,
  custom_symbol                TEXT,
  isin                         TEXT,
  instrument                   TEXT,
  sebi_tax                     NUMERIC(18, 6),
  stt                          NUMERIC(18, 6),
  brokerage_charges            NUMERIC(18, 6),
  service_tax                  NUMERIC(18, 6),
  exchange_transaction_charges NUMERIC(18, 6),
  stamp_duty                   NUMERIC(18, 6),
  create_time                  TEXT,
  update_time                  TEXT,
  drv_expiry_date              TEXT,
  drv_option_type              TEXT,
  drv_strike_price             NUMERIC(18, 4),
  raw_payload                  JSONB NOT NULL,
  sync_run_id                  BIGINT REFERENCES sync_runs(id),
  created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id)
);

CREATE TRIGGER trg_dhan_trades_updated_at
  BEFORE UPDATE ON dhan_trades
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_dhan_trades_exchange_time ON dhan_trades (exchange_time);
CREATE INDEX idx_dhan_trades_security_id ON dhan_trades (security_id);
CREATE INDEX idx_dhan_trades_isin ON dhan_trades (isin);

CREATE TABLE holdings_current (
  security_id       TEXT PRIMARY KEY,
  trading_symbol    TEXT,
  isin              TEXT,
  exchange          TEXT,
  total_qty         INTEGER,
  dp_qty            INTEGER,
  t1_qty            INTEGER,
  mtf_t1_qty        INTEGER,
  mtf_qty           INTEGER,
  available_qty     INTEGER,
  collateral_qty    INTEGER,
  avg_cost_price    NUMERIC(18, 4),
  last_traded_price NUMERIC(18, 4),
  raw_payload       JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_holdings_current_updated_at
  BEFORE UPDATE ON holdings_current
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
