-- Phase 3 — FIFO lot engine tables

CREATE TABLE lots (
  id                  BIGSERIAL PRIMARY KEY,
  isin                TEXT NOT NULL,
  security_id         TEXT,
  custom_symbol       TEXT,
  purchase_date       TIMESTAMPTZ NOT NULL,
  lt_conversion_date  DATE NOT NULL,
  original_quantity   INTEGER NOT NULL CHECK (original_quantity > 0),
  remaining_quantity  INTEGER NOT NULL CHECK (remaining_quantity >= 0),
  cost_per_share      NUMERIC(18, 4) NOT NULL,
  cost_basis_unknown  BOOLEAN NOT NULL DEFAULT false,
  source_trade_id     BIGINT NOT NULL REFERENCES dhan_trades(id),
  status              TEXT NOT NULL CHECK (status IN ('open', 'closed')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_lots_updated_at
  BEFORE UPDATE ON lots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_lots_isin ON lots (isin);
CREATE INDEX idx_lots_status ON lots (status);
CREATE INDEX idx_lots_source_trade_id ON lots (source_trade_id);

CREATE TABLE lot_allocations (
  id              BIGSERIAL PRIMARY KEY,
  sell_trade_id   BIGINT NOT NULL REFERENCES dhan_trades(id),
  lot_id          BIGINT NOT NULL REFERENCES lots(id),
  quantity        INTEGER NOT NULL CHECK (quantity > 0),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_lot_allocations_updated_at
  BEFORE UPDATE ON lot_allocations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_lot_allocations_sell_trade_id ON lot_allocations (sell_trade_id);
CREATE INDEX idx_lot_allocations_lot_id ON lot_allocations (lot_id);
