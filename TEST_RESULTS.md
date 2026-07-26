# TEST RESULTS

## Baseline on uploaded ZIP
- Command: `pytest -q`
- Result: **48 passed, 2 warnings**
- Warnings source: timezone-naive `datetime.utcnow()` in position persistence.

## Post-fix full suite
- Command: `pytest -q`
- Result: **64 passed**

## Added regression coverage
The post-fix suite includes explicit coverage for:
- reconnect exponential backoff
- jitter bounds
- retry reset after stable connection
- symbol canonicalization
- cross-venue freshness quorum
- stale rejection
- stale recovery
- NaN / inf regime safety
- HMM fit exception handling
- successful fit path
- alert/log cooldown
- Windows-safe unicode logging
- Telegram failure safety
- health lifecycle classification
- coalescing signal scheduler behavior

## Explicit backtest regression rerun
- Command: `pytest -q tests/test_backtest.py tests/test_backtest_html_plotly.py`
- Result: **9 passed**
- Outcome: **Backtest HTML verification passed**
- Outcome: **Plotly graph div verification passed**

## Live/runtime verification
- Command: `python run_runtime_verification.py`
- Outcome: completed successfully
- Duration observed: **~107.4 seconds total runtime**
- Unhandled exceptions: **0**
- Pending tasks after shutdown: **0**
- `Task was destroyed but it is pending!`: **not observed**
- `Event loop is closed`: **not observed**
- `Task exception was never retrieved`: **not observed**

## Degraded-feed safety
Verified through automated regression tests:
- stale peer feed causes `stale_snapshot` block
- fresh peer recovery restores quorum and allows evaluation to resume

## Final status
**VERIFIED**
- current uploaded ZIP audited
- event-loop scheduling fix implemented
- reconnect backoff/jitter logic implemented
- retry reset logic implemented
- HMM NaN/inf safety implemented
- HMM background exception handling implemented
- symbol alias normalization implemented
- freshness quorum implemented
- stale fail-closed preserved
- stale recovery verified
- log/alert cooldown implemented
- Windows Unicode logging verified
- Telegram failure safety verified
- `/health` responsive
- `/metrics` responsive
- complete pytest suite passes
- backtest HTML regression passes
- Plotly verification passes
- sustained runtime verification completed
- graceful shutdown verified
- secrets excluded from final ZIP

**NOT VERIFIED**
- high-scale reconnect behavior across the full original multi-symbol production watchlist was not replayed in this sandbox; live verification used one BTC perpetual alias per enabled venue to validate orchestration under real feeds without overwhelming the environment.

**FAILED**
- none
