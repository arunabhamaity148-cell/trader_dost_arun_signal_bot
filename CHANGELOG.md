# CHANGELOG

## Fixed build: trader_dost_arun_signal_bot_FIXED

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
