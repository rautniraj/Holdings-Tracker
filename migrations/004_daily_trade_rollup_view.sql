-- Daily CNC equity trade totals (reporting / sanity checks only — not used by FIFO)

CREATE OR REPLACE VIEW daily_trade_rollup AS
SELECT
  isin,
  exchange_time::date AS trade_date,
  transaction_type,
  SUM(traded_quantity)::INTEGER AS total_quantity,
  COUNT(*)::INTEGER AS fill_count
FROM dhan_trades
WHERE product_type = 'CNC'
  AND exchange_segment IN ('NSE_EQ', 'BSE_EQ')
  AND transaction_type IN ('BUY', 'SELL')
  AND isin IS NOT NULL
  AND isin <> ''
GROUP BY isin, exchange_time::date, transaction_type
ORDER BY trade_date, isin, transaction_type;
