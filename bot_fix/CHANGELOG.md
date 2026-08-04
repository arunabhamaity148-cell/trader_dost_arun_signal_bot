# CHANGELOG

## FIXED5 — production hardening (this build)

### Performance (closes the pre-fix loop-lag/RSS soak failure)
- Per-(venue:symbol) `KeyedSeries` rolling aggregates maintained O(1) on
  `add_snapshot`/`add_trade`; `MarketStateStore.view()` and the percentile
  helpers now read bounded windows instead of rescanning the full deque.
  `view()` 17.9 ms → 0.30 ms; percentile pair 8.2 ms → 1.5 ms.
- `_zscore` vectorized with numpy (with optional window cap); `atr` and other
  "last-N" features slice to the required tail. `compute_features` 37 ms → 6.5 ms.
- `app._build_feature_inputs` builds the own FeatureSet fully and a minimal
  FeatureSet per peer (premium/delta_oi only): 154 ms → 4.35 ms.

### Trading safety (fail-closed)
- `RiskEngine.is_valid_signal()` rejects entry<=0, wrong-side stop, no target,
  or degenerate range before sizing.
- `register_outcome()` books realized_r = 0 for degenerate positions instead of
  dividing by ~0 and poisoning risk stats.
- Kill switch + consecutive-loss counter are a **latch**: restored
  unconditionally from checkpoint and no longer cleared at the UTC day boundary;
  only `reset_kill_switch()` clears them. Daily PnL accumulators still reset
  daily.
- Leverage is computed once via shared `advisory_leverage()` and mirrored into
  `signal.metadata["leverage"]`, so the displayed and modeled leverage agree.

### Operator controls
- New shared `OperatorState` (`core/operator_state.py`) is the single source of
  truth for pause/resume/mute, injected into both `SignalEngine` and
  `TelegramAdminBot`. `/pause` and `/resume` now actually affect the live
  signal path (previously a silent no-op). Added `/paused`.
- `SignalEngine.engine_stats()` feeds `/status` with live kill_switch / daily R
  / open positions / paused list.
- `/mute` tolerates non-numeric input.

### Reliability
- `StateCheckpoint.save()` writes to `.tmp` then `os.replace()`; `load_latest()`
  falls back to `.bak` or `{}` on any parse error. A torn write can no longer
  crash boot.
- `PositionStore` opens with WAL + busy_timeout, enters `_degraded` mode on
  init/read failure, and never raises out of a corrupt DB.
- `app.py` installs SIGINT/SIGTERM handlers → graceful `stop()` on VPS stop.
- HMM `_fit_task` consume path guarded by an asyncio Lock; `close()` cancels
  outstanding fits.
- SQLite persistence (position open/close, checkpoint) moved off the event loop
  via `asyncio.to_thread`.
- Exposure reads use `open_positions_snapshot()`; mutations happen under an
  asyncio Lock.

### Security
- `OpsHttpServer` binds `127.0.0.1` by default (`ops.bind_host` overridable);
  request line capped at 4096 bytes with a 5s read/write timeout.
- `TelegramAlerter` uses a single pooled `httpx.AsyncClient` (was one per send);
  `aclose()` on shutdown.

### Quality
- Removed dead `newsguard/llm_classifier.py` and its test (no callers).
- `deterministic.py` strategy config reads hardened with `.get(key, default)`.
- `validate_config()` at startup fails fast on missing/invalid config sections.
- Split `requirements.txt` (live runtime) from `requirements-dev.txt`
  (pytest, plotly, shap).

### Tests
- Added `test_kill_switch_latch_survives_day_boundary_but_daily_pnl_resets` and
  `test_kill_switch_latch_requires_operator_reset_to_clear`.
- Full suite: 111 passed (3-test delta vs 113 baseline = deleted dead-LLM test).

---

## Fixed build: trader_dost_arun_signal_bot_FIXED (prior session)

### Runtime orchestration
- Replaced inline per-event signal evaluation in `app.py` with a coalescing `SignalEvaluationScheduler`.
- Preserved real-time state ingestion while throttling expensive per-symbol evaluation work.
- Added runtime counters for queue events, signal evaluations, veto reasons, sockets, and peak task count.
- Improved `/health` payload structure with lifecycle `phase` (`starting`, `warmup`, `healthy`, `degraded`).

### Connector reliability
- Added bounded exponential reconnect backoff with jitter in `trader_dost_arun/data/base.py`.
- Added retry reset after stable connection windows.
- Added reconnect instrumentation fields: venue, symbol, connection_id, reason, uptime, last_message_age, attempt, backoff.
- Connector shutdown now closes websocket, background tasks, and HTTP clients explicitly.
- `ConnectorManager` now owns connector instances and performs orderly shutdown.

### Cross-venue peer normalization
- Added `trader_dost_arun/core/symbols.py`.
- Reworked `MarketStateStore.peer_views()` to use canonical instrument identity instead of exact symbol equality.
- Added freshness quorum evaluation via `MarketStateStore.freshness()`.

### Numerical safety / regime handling
- Added finite-value validation and sanitization to feature calculations.
- Hardened realized volatility, VWAP, volume-profile, ATR, and z-score inputs.
- Reworked `HMMRegimeDetector` to reject invalid samples, sanitize fit matrices, consume background task results, and fail safely to fallback regime.

### Safety vetoes
- Added explicit `stale_snapshot` quorum-based veto in `trader_dost_arun/signals/vetoes.py`.
- Preserved fail-closed behavior while allowing freshness recovery after fresh peer snapshots arrive.

### Alerting / logging
- Added reusable cooldown deduper in `trader_dost_arun/ops/logging_utils.py`.
- Rate-limited repeated suppression logs and health alerts without weakening safety checks.
- Added `SafeStreamHandler` for Windows/legacy console unicode safety.
- Configured UTF-8 file logging explicitly.

### Telegram hardening
- Telegram startup now logs `ENABLED` or `DISABLED - safe reason` without revealing secrets.
- Telegram send/poll failures are caught and logged without crashing the engine.
- Added `TELEGRAM_ADMIN_CHAT_ID` to `.env.example`.

### Persistence / hygiene
- Replaced deprecated `datetime.utcnow()` persistence writes with timezone-aware UTC timestamps.
- Final packaging excludes `.env`, sqlite/db files, logs, caches, backtest artifacts, and virtualenv directories.

### Tests added
- `tests/test_reconnect_backoff.py`
- `tests/test_symbol_alias_freshness.py`
- `tests/test_regime_safety.py`
- `tests/test_logging_and_telegram_safety.py`
- `tests/test_stale_health_and_scheduler.py`

### Verification summary
- Baseline uploaded ZIP: **48 passed, 2 warnings**
- Final fixed suite: **64 passed**
- Explicit backtest regressions: **9 passed**
- Sustained runtime verification completed successfully
