# Binance USDⓈ-M Futures Research Scanner

**Research only. No orders are placed. No guaranteed same-day fills or 5% net returns.**

## Current validation status
- Hourly scanner: implemented; actual GitHub Actions success after latest changes **not yet verified**.
- Candidate calculation: implemented; signals remain disabled via `signal_status=DISABLED_PENDING_PAPER_VALIDATION`.
- Paper-fill tracking: implemented in `paper_validate.py`; actual fills and tracking success **not yet verified**.
- Deterministic unit tests: written, configured in Actions; actual passing result **not yet verified**.
- Walk-forward backtest: implemented in `backtest.py`; historical datasets and performance results **not yet collected**.
- Market source can fail due Binance HTTP 451 / mirror HTTP 503. Partial results must never be treated as a complete scan.

## Run
```bash
python -m py_compile scanner.py paper_validate.py backtest.py
python -m unittest discover -s tests -p 'test_*.py'
python scanner.py
python paper_validate.py
```

Run offline historical replay with **genuine Binance kline JSON arrays**:
```bash
python backtest.py --symbol ETHUSDT --h1 history/ETHUSDT-1h.json --h4 history/ETHUSDT-4h.json
```
The JSON inputs must contain full Binance kline arrays, including open time, OHLC, quote volume (index 7) and candle close time (index 6). Files are not bundled; do not fabricate historical returns.

## Interpretation
- `data/latest.json`: scan timestamp, coverage, errors, `research_candidates` and disabled `trade_screen`.
- `data/paper_ledger.json`: chronological simulated fills, if generated.
- `data/backtest_result.json`: offline walk-forward summary, if a historical replay has actually been run.
- Historical OHLC does not prove the intrabar event order. The validator deliberately assumes the stop wins when stop and TP both appear in the same later bar; a TP in the entry bar is not credited.
- One-hour bars cannot accurately establish fill order within an hour or the exact 23:59 KST exit. Open positions at expiry are recorded as unresolved rather than silently credited as profits.
- Quoted costs are estimates, not actual Binance fills or realized fees. Full backtesting requires instrument-specific fees, exchange filters, realistic execution latency, funding timestamps, market impact, out-of-sample and forward paper testing.
- Scanner checks nominal reward-to-risk and movement-distance constraints. ATR **does not estimate** probability of reaching a target. No verified win rate, positive expectancy, or same-day completion rate is claimed.

## GitHub Actions
`.github/workflows/scan.yml` runs hourly at UTC minute 31, runs unit tests, refreshes the snapshot, attempts paper tracking, and commits resulting JSON. If API data is incomplete, the workflow is marked failed. Manual execution is available through the Actions UI.

## Required before enabling actionable recommendations
1. Successful workflow run and reliable all-symbol coverage.
2. Sufficient out-of-sample history with time-ordered entry, stop, target, and forced-end-of-day handling.
3. Forward paper results, fill rate, net expectancy, drawdown and execution cost validation.
4. Confirm current price, exchange tick/step sizes and order book at decision time.
5. Enforce per-trade account risk <=1%, 3x isolated leverage and intraday expiration.
