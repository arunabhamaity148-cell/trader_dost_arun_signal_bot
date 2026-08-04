# RUNTIME VERIFICATION

This file records what was actually verified on this build, with the method and
the numbers, and explicitly distinguishes what still needs live verification on
the target VPS.

## Environment
- Python 3.11 (venv), Windows 10 / Git Bash sandbox.
- Runtime deps from `requirements.txt` installed cleanly (httpx 0.27.2, websockets 12.0,
  numpy 1.26.4, scikit-learn 1.5.2, hmmlearn 0.3.2, pandas 2.2.2, scipy 1.13.1,
  prometheus-client 0.21.0, sentence-transformers 3.2.0, lightgbm 4.5.0).
- No exchange connectivity from this sandbox; soak uses a synthetic producer
  against the real app code path.

## Clean install
- `python -m venv` → `pip install -r requirements.txt` → **PASS**.
- `pytest -q` → **111 passed** (3 removed with the deleted dead-LLM module; all
  other tests retained and green).

## Hot-path microbenchmarks (3000-element rolling history, 5 venues)

| Work item | Pre-fix | Post-fix | Ratio |
|---|---:|---:|---:|
| `MarketStateStore.view()` per call | 17.9 ms | 0.30 ms | ~60× |
| `spread_percentile + same_side_depth_percentile` (per candidate) | 8.2 ms | 1.5 ms | ~5× |
| `compute_features()` own side | 37 ms | 6.5 ms | ~5.7× |
| `app._build_feature_inputs` (own + 5 peers) | 154 ms | 4.35 ms | ~35× |
| `atr()` on 3000 history | ~7 ms | ~0.1 ms | ~70× |

These were the four calls executed on every evaluation tick; the reduction is
why event-loop lag no longer scales with `history_size`.

## 60-second synthetic soak (real app pipeline)
- `python run_soak_synthetic.py 60 400` (real TradingApplication; exchange
  connectors replaced by a 400 ev/s producer over the full 5-venue × 10-symbol
  watchlist). See `SOAK_TEST_RESULTS.md` for the per-5s checkpoint table.

Headline: **0 unexpected exceptions, 0 dropped events, RSS plateaued ≈180 MB,
task count stable (12–19), queue HWM pinned at 448/5000, graceful SIGTERM
shutdown within timeout.** Loop-lag p95 oscillated 311–563 ms at the synthetic
over-drive and **did not trend upward** over the run — the monotone pre-fix
climb is gone.

## Component checks performed

- **Bounded queue burst test:** 10000 same-key snapshots put+coalesced; consumer
  drained without dropping. Drop counters zero.
- **Ops HTTP localhost binding:** `OpsHttpServer(host="127.0.0.1")` confirmed to
  bind 127.0.0.1 and serve `/health` over a local TCP connection.
- **Pause/resume round-trip:** `OperatorState.pause/resume/paused_strategies`
  verified end-to-end; `SignalEngine.evaluate()` suppresses a paused strategy
  with `suppressed_reason="strategy_paused"`.
- **Kill-switch latch:** regression test proves the latch survives a simulated
  UTC midnight and a restart; only `reset_kill_switch()` clears it.
- **Degenerate-signal veto:** unit tests assert invalid (entry<=0, wrong-side
  stop, no target, degenerate range) signals are rejected before sizing.
- **Checkpoint corruption tolerance:** writing a truncated `checkpoint.json`
  then booting returns empty state instead of crashing.
- **Persistence DB corruption tolerance:** corrupt SQLite → `PositionStore`
  enters degraded mode, returns empty structures, does not raise.

## STILL TO VERIFY ON TARGET (not claimable from this sandbox)
- A **live** 60-second smoke and a 15-minute + multi-hour live exchange soak
  using `run_live_smoke_60s.py` / `run_live_soak_15m.py` on the deployment VPS.
- Loop-lag p95 < 250 ms under the real exchange feed rate (the synthetic soak
  intentionally over-drives ingestion; live feed rate is typically much lower).
- Long-horizon RSS plateau (24h+) — this build fixes the O(history) RSS driver;
  a multi-day live confirmation is the final acceptance gate before real money.
