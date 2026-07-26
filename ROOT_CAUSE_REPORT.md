# ROOT CAUSE REPORT

## Scope
This report documents the fixes applied to the uploaded `trader_dost_arun_signal_bot-main.zip` working copy, not to any previous temporary sandbox tree.

## 1. Event-loop load / reconnect churn
**Status: VERIFIED by code inspection, then live post-fix stability verified.**

### Root cause
`app.py` previously consumed every queue event inline and ran the full signal pipeline directly on the main asyncio loop for each `MarketSnapshot`, `Trade`, and `LiquidationEvent`.
That design combined:
- high-frequency websocket ingestion,
- synchronous feature calculation,
- peer feature fan-out,
- regime updates,
- veto/risk/strategy evaluation,
- alert/log handling,

inside the same latency-sensitive event loop path.

With one connector task per `venue × symbol`, this made receive loops vulnerable to starvation and stale-state cascades under load.

### Fix
- Replaced direct per-event inline evaluation with a **coalescing signal-evaluation scheduler**.
- Kept **state ingestion real-time**, but moved expensive feature fan-out off the hot ingest path.
- Added a **controlled per-symbol evaluation cadence** (`system.signal_evaluation_interval_seconds`).
- Coalesced bursty event streams so trade/liquidation bursts do not trigger redundant full evaluations.
- Kept open-position monitoring on snapshot updates.
- Added runtime counters for evaluations, blocks, sockets, tasks, and health.

### Connector hardening
- Added structured reconnect instrumentation with:
  - venue
  - symbol
  - connection_id
  - reason
  - uptime
  - last_message_age
  - attempt
  - backoff
- Added **bounded exponential backoff with jitter**.
- Added **retry reset after a stable connection window**.
- Connector shutdown now closes websocket/client resources cleanly.

### Evidence
- Full live verification completed with **5 live sockets** and **0 reconnects**.
- `/health` and `/metrics` remained responsive throughout the run.
- No `Task was destroyed but it is pending!`
- No `Event loop is closed`
- No `Task exception was never retrieved`

## 2. Cross-venue symbol alias / freshness quorum
**Status: VERIFIED by code inspection and regression tests.**

### Root cause
`MarketStateStore.peer_views()` previously matched peers by exact symbol string equality. That broke cross-venue reasoning for equivalent perpetual instruments such as:
- `BTCUSDT`
- `BTC-USDT-SWAP`
- `BTC-PERP`
- `BTC-PERPETUAL`

### Fix
- Added `trader_dost_arun/core/symbols.py` with structured instrument normalization.
- Normalization now reasons about:
  - base asset
  - quote asset / quote class
  - instrument type
- `peer_views()` now groups peers by canonical instrument identity instead of raw string equality.
- Added explicit **freshness quorum** logic in `MarketStateStore.freshness()`.
- `stale_snapshot` safety is preserved and now uses canonical peer identity correctly.

### Evidence
Regression tests cover:
- alias normalization
- peer alias recovery
- quorum degradation
- quorum recovery
- stale block / stale recovery

## 3. HMM / regime NaN crash
**Status: VERIFIED by code inspection and regression tests.**

### Root cause
The regime detector could accept invalid numerical inputs into its sample matrix and background HMM fit path. That created two risks:
- `hmmlearn` fit failures from `NaN` / `inf`
- background task failures surfacing as `Task exception was never retrieved`

### Fix
- Added validation for regime samples before insertion.
- Invalid numerical samples are **rejected**, not coerced into fake values.
- Fit matrices are sanitized to finite rows only.
- If valid sample history is insufficient, detector stays in the safe fallback / warmup regime.
- Background fit task completion is explicitly consumed and exceptions are handled.
- Prediction failures now fall back safely without leaking task exceptions.

### Evidence
Regression tests cover:
- NaN rejection
- inf rejection
- insufficient-history fallback
- fit-exception handling
- successful fit path

## 4. Log / Telegram alert spam
**Status: VERIFIED by prior runtime evidence and fixed.**

### Root cause
Repeated warning paths could emit the same health/suppression messages many times in tight loops.

### Fix
- Added reusable `CooldownDeduper`.
- Applied cooldown-based deduplication to:
  - repeated suppression logs
  - repeated Telegram health alerts
  - repeated Telegram-disabled status logs
- Safety checks still run every cycle; only the **notification/log emission** is cooled down.

## 5. Windows Unicode logging
**Status: VERIFIED by code inspection and regression tests.**

### Root cause
Standard console logging could raise `UnicodeEncodeError` on Windows consoles with limited encodings when emoji/unicode log messages were emitted.

### Fix
- Added `SafeStreamHandler` with encoding fallback using `backslashreplace`.
- Explicitly configured file handlers with `encoding="utf-8"`.
- Disabled logging exception propagation from interfering with the app.

## 6. Graceful shutdown / resource ownership
**Status: VERIFIED in live runtime verification.**

### Root cause
Connector shutdown relied too heavily on task cancellation instead of explicit resource stop ownership.

### Fix
- `ConnectorManager` now owns connector instances and stops them explicitly.
- Connectors close websocket + background tasks + HTTP client cleanly.
- App shutdown now stops, in order:
  1. evaluation scheduler
  2. background consumer/health tasks
  3. Telegram bot
  4. HTTP ops server
  5. NewsGuard
  6. external context client
  7. connector manager

## 7. Health / metrics classification
**Status: VERIFIED by tests and live verification.**

### Improvements
- Added startup/warmup/healthy/degraded health classification.
- Avoided misleading percentile handling for tiny sample sets.
- `/health` now distinguishes operational status from lifecycle phase.
- `/metrics` remained responsive during the sustained run.

## 8. Telegram failure safety
**Status: VERIFIED by regression tests and code inspection.**

### Fix
- Startup logs clearly state `Telegram ENABLED` or `Telegram DISABLED - safe reason`.
- Telegram send/poll failures are caught and logged without crashing the engine.
- No secrets are logged.

## 9. Security / secrets
**Status: VERIFIED for delivered artifact.**

### Fix
- Preserved `.env.example` as the safe template.
- Added `TELEGRAM_ADMIN_CHAT_ID` to `.env.example`.
- Final packaging excludes real `.env`, sqlite databases, logs, caches, and virtualenv files.

## Acceptance summary
- Event-loop starvation design issue: **fixed**
- Symbol aliasing / freshness quorum: **fixed**
- HMM NaN / background exception risk: **fixed**
- Alert/log spam: **fixed**
- Windows unicode logging: **fixed**
- Graceful shutdown: **verified live**
- Secrets in final ZIP: **excluded**
