# Root Cause Report

## Final status
Repaired and test-verified in the sandbox. Live smoke test passed for a short public-market-data run. A 15-minute full-watchlist soak test was **not run** in this environment, so this repository is **not** marked production-ready.

## Confirmed root causes and repairs

### 1. Core freshness was coupled to optional enrichment
- **Root cause:** optional REST enrichment snapshots reused the same `MarketSnapshot` channel as websocket market data, so enrichment updates could make a stale feed appear fresh.
- **Affected files:** `trader_dost_arun/core/models.py`, `trader_dost_arun/core/state.py`, `trader_dost_arun/data/base.py`, `app.py`
- **Repair:** added explicit `core_event_time`, `core_arrival_time`, `enrichment_event_time`, `enrichment_arrival_time`, and `update_class` fields; changed freshness evaluation to age only the last valid core market update; exposed enrichment/core age diagnostics.
- **Why this works:** optional OI/options/context updates no longer refresh core market freshness, so stale core data remains fail-closed while fresh core + stale optional data stays usable.
- **Remaining limitation:** strategies still consume merged snapshots, but freshness gating now differentiates required vs optional inputs.

### 2. Reconnect control lacked systemic network/DNS degradation awareness
- **Root cause:** connectors treated venue-local failures and cross-venue transport failures the same way, so repeated DNS/timeout/connect failures could trigger aggressive reconnect behavior.
- **Affected files:** `trader_dost_arun/ops/latency.py`, `trader_dost_arun/data/base.py`, `app.py`
- **Repair:** added systemic transport-error classification, cross-venue degradation detection, recovery tracking, active-connection ownership tracking, and degraded reconnect backoff handling.
- **Why this works:** the runtime now distinguishes likely global network degradation from venue-local instability and lengthens recovery cadence during degraded periods.
- **Remaining limitation:** this is heuristic detection based on recent failures and venue diversity, not an external network probe.

### 3. Connector/task ownership and shutdown idempotence were weak
- **Root cause:** connector startup was not idempotent, duplicate feed definitions could create duplicate loops, and cancellation semantics could propagate noisy shutdown behavior.
- **Affected files:** `trader_dost_arun/data/manager.py`, `trader_dost_arun/ops/latency.py`, `app.py`, venue connector pollers
- **Repair:** made manager startup idempotent, deduplicated watchlist feeds, tracked active connection owners, made poller sleeps stop-aware, and changed `run_forever()` / `stop()` to drain cleanly and idempotently.
- **Why this works:** duplicate connector loops are prevented at manager level, reconnects are suppressed after shutdown, and background tasks drain with `gather(..., return_exceptions=True)`.
- **Remaining limitation:** the architecture still uses one websocket per feed; this repair focuses on bounded/recoverable behavior rather than a full venue-specific multiplex refactor.

### 4. REST enrichment pressure was only partially controlled
- **Root cause:** per-symbol enrichment loops shared no pacing or circuit-breaking beyond basic retries.
- **Affected files:** `trader_dost_arun/data/base.py`, venue connector modules
- **Repair:** added shared per-venue semaphore use, per-venue request pacing, bounded retry budgets, circuit-breaker cooldown, transport-failure classification, and stop-aware polling.
- **Why this works:** optional enrichment can no longer burst unbounded concurrent requests or keep hammering a failing venue during repeated transport errors.
- **Remaining limitation:** enrichment polling is still connector-local, not a single centralized per-venue poller.

### 5. Logging integrity and secret redaction were incomplete
- **Root cause:** logging did not guarantee single-line records and traceback/credential redaction coverage was incomplete.
- **Affected files:** `trader_dost_arun/ops/logging_utils.py`
- **Repair:** added queue-based logging fan-in, single-line sanitizing formatters, traceback sanitization, Telegram token/chat-id redaction, URL credential redaction, query/header/bearer redaction.
- **Why this works:** concurrent log writes now serialize through a queue listener and all rendered output is sanitized before emission.
- **Remaining limitation:** application code that prints directly to stdout/stderr outside logging is not intercepted.

### 6. NewsGuard source failures needed stronger isolation
- **Root cause:** malformed/empty/unavailable sources could fail repeatedly without explicit per-source cooldown state.
- **Affected files:** `trader_dost_arun/newsguard/sources.py`, `trader_dost_arun/newsguard/guard.py`
- **Repair:** added source health state, cooldown/backoff, retry-budget tracking, skip-during-cooldown behavior, calendar-source isolation, and per-item normalization failure isolation.
- **Why this works:** one broken RSS/Telegram/on-chain source no longer spams retries or blocks other sources and refresh passes.
- **Remaining limitation:** cooldown state is in-memory and resets on process restart.

### 7. Clean-environment import resilience for dotenv
- **Root cause:** repository import failed immediately when `python-dotenv` was absent even though `.env` loading is optional for tests and some runtime paths.
- **Affected files:** `trader_dost_arun/core/config.py`, `requirements.txt`
- **Repair:** kept `python-dotenv` declared in `requirements.txt` and added a safe fallback no-op loader if the dependency is unavailable.
- **Why this works:** test/import paths no longer hard-fail solely because `.env` support is missing, while real environments still use `python-dotenv` when installed.
- **Remaining limitation:** a truly clean production deployment should still install dependencies from `requirements.txt`.

## Trading-logic preservation
No signal thresholds, direction rules, TP/SL rules, leverage formulas, risk-engine rules, NewsGuard decision rules, or watchlist semantics were intentionally changed. Repairs were limited to infrastructure, freshness semantics, retries, shutdown behavior, and observability.

## Not fully completed in this environment
- No full 15-minute full-watchlist soak run
- No clean-room `pip install -r requirements.txt` completion inside this sandbox (attempt timed out)
- No venue-specific websocket multiplex refactor

## Resulting status
**REPAIRED — PARTIALLY VERIFIED**
