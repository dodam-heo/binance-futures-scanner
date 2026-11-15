# Binance Futures Scanner
Public-data-only research collector for Binance USDⓈ-M USDT perpetual futures. No keys, no order execution.
Runs hourly at minute 31 UTC (same minute KST) and on manual workflow dispatch.
- Fetches exchangeInfo and all TRADING / PERPETUAL / USDT contracts.
- Fetches all 24h tickers and stores full market metrics.
- Analyzes 30 liquid/active contracts using closed 1h and 4h OHLCV, ATR14, SMA20/50 and 20-candle highs/lows.
- Writes data/latest.json with UTC timestamp, status and completeness. Fails visibly on incomplete scans.
- **Does not produce trade recommendations**: funding, order-book spread/slippage and entry-before-target feasibility must still be verified before any order recommendation.
- GitHub-hosted runner can also receive HTTP 451. Check Actions logs; a failed workflow is not a successful market scan.
