# Runtime Verification

## Final runtime status
**PARTIALLY VERIFIED**

A short live smoke test against public market-data venues succeeded. A required 15-minute full-watchlist soak test was **not run** in this sandbox, so the repository is **not** marked production-ready.

## Smoke test
### Command
```bash
python3 run_smoke_verification.py > smoke_output.json
```

### Scope
- Duration: ~20 seconds live runtime (+ startup/shutdown overhead)
- Watchlist used:
  - Binance: `BTCUSDT`
  - Bybit: `BTCUSDT`
  - OKX: `BTC-USDT-SWAP`
- No trading credentials used
- No order placement attempted

### Smoke result
**PASS**

### Observed quantitative metrics
From `smoke_output.json`:
- Runtime duration: **28.48s**
- Queue events processed: **1777**
  - Snapshots: **1242**
  - Trades: **535**
- Events/sec: **62.40**
- Queue high-water mark: **108**
- Peak task count: **15**
- Signals evaluated: **60**
- Signals emitted: **0**
- Healthy snapshot evaluations: **60**
- Unexpected exceptions: **0**
- Network degraded transitions: **0**
- Reconnect count by venue: **0** during smoke window
- Health phase: **healthy**
- Event-loop lag p95: **2.08 ms**
- Evaluation latency p95: **70.35 ms**

### Venue health during smoke
- Binance: healthy, score **98.55**, p95 latency **80.35 ms**, samples **453**
- Bybit: healthy, score **98.72**, p95 latency **81.78 ms**, samples **978**
- OKX: healthy, score **98.53**, p95 latency **86.97 ms**, samples **318**

### Observed optional-enrichment limitation
- Binance open-interest REST polling returned HTTP **451** in this environment.
- The poll failure was isolated and did **not** crash websocket ingestion, signal evaluation, health reporting, or shutdown.

## Shutdown verification
### Result
**PASS** for the smoke-run path

### Observed properties
- Application stopped without `KeyboardInterrupt` traceback from the smoke script
- No `CancelledError` traceback surfaced during normal shutdown
- Runtime snapshot after shutdown showed no active sockets in the manager
- No unexpected exceptions were recorded

## 15-minute full-watchlist soak test
### Result
**NOT RUN**

### Reason
This sandbox session prioritized code repair, regression coverage, and artifact validation. A 15-minute full-watchlist public-network soak was not completed within the available execution budget.

## Known runtime limitations
1. No full-watchlist 15-minute soak evidence in this package
2. No venue-specific websocket multiplex refactor was implemented
3. Clean-room dependency installation was not fully completed in the sandbox because the full `pip install -r requirements.txt` attempt timed out
4. Public REST enrichment can still be venue-blocked externally (example: Binance HTTP 451), but failures are now isolated from core ingestion

## Final runtime classification
**REPAIRED — PARTIALLY VERIFIED**
