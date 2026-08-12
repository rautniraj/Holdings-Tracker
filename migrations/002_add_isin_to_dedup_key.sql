-- Add isin to dhan_trades dedup key (IPO rows have order_id/security_id = "0")

UPDATE dhan_trades
SET isin = raw_payload->>'isin'
WHERE isin IS NULL
  AND raw_payload->>'isin' IS NOT NULL
  AND raw_payload->>'isin' <> '';

ALTER TABLE dhan_trades
  DROP CONSTRAINT IF EXISTS dhan_trades_order_id_exchange_time_transaction_type_traded__key;

ALTER TABLE dhan_trades
  DROP CONSTRAINT IF EXISTS dhan_trades_order_id_exchange_time_transaction_type_traded_quantity_traded_price_security_id_key;

ALTER TABLE dhan_trades
  ADD CONSTRAINT dhan_trades_dedup_key
  UNIQUE (order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin);
