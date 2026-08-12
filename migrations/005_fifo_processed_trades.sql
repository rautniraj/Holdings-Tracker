-- Incremental FIFO — track processed trades and engine state

CREATE TABLE fifo_processed_trades (
  trade_id     BIGINT PRIMARY KEY REFERENCES dhan_trades(id) ON DELETE CASCADE,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_fifo_processed_trades_processed_at
  ON fifo_processed_trades (processed_at);

CREATE TABLE fifo_state (
  id                   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  lt_rules_hash        TEXT,
  last_full_rebuild_at TIMESTAMPTZ,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO fifo_state (id) VALUES (1);

CREATE TRIGGER trg_fifo_state_updated_at
  BEFORE UPDATE ON fifo_state
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
