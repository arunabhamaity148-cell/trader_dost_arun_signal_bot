# ARCHITECTURE CHANGES

## 1) Bounded grouped websocket topology retained and verified
The repository keeps the grouped/multiplexed connector design and does **not** revert to one websocket per venue × symbol.

Verified default topology on the live default watchlist:
- Binance: **2** grouped sockets
- Bybit: **2** grouped sockets
- OKX: **2** grouped sockets
- Hyperliquid: **2** grouped sockets
- Deribit: **1** grouped socket
- Total: **9 sockets**

## 2) Market ingress changed from blocking FIFO to bounded latest-state semantics
`ConnectorManager` now owns a dedicated bounded market-ingress queue implementation instead of a plain `asyncio.Queue`.

### New behavior
- snapshots are coalesced by `venue:symbol`
- the newest snapshot supersedes older pending snapshots for the same feed
- trade / liquidation flow remains bounded
- overload is observable through runtime counters
- connectors no longer need to block on stale snapshot buildup before the consumer catches up

### New runtime counters
`runtime_snapshot()` and `/health` now include `queue_overload`, exposing:
- `coalesced_snapshots`
- `dropped_snapshots`
- `dropped_trades`
- `dropped_liquidations`
- `dropped_total`
- snapshot/critical depths and capacities

## 3) Explicit heartbeat ownership
Connector sockets now disable websocket-library auto-pings and use the application-owned recv-timeout / ping-probe path as the sole liveness owner.

Why this matters:
- reduces split ownership between library keepalive and app keepalive
- makes timeout reasoning deterministic
- avoids overlapping ping strategies across grouped feeds

## 4) Systemic disconnect classification widened
Abnormal close reasons and heartbeat timeouts now participate in the same network-degraded coordination path as transport/DNS failures.

This improves shared-cause handling for:
- abnormal websocket close waves
- transient infra / DNS / routing degradation
- reconnect coordination across venues

## 5) External context hardening
The optional external-context subsystem was changed to:
- isolate failures per component
- log concise component-specific diagnostics
- degrade bootstrap failures instead of aborting startup
- retain cooldown/backoff state internally

This keeps optional enrichment from destabilizing core market ingestion.

## 6) Telegram disabled-state deduplication
Application startup remains the single source of truth for Telegram enabled/disabled status. The admin-bot component now silently no-ops when unconfigured.

## 7) Portable RSS telemetry
RSS collection now supports:
- Linux `/proc/self/status`
- Windows `GetProcessMemoryInfo`
- `resource.getrusage(...)` fallback where available

## 8) Regression suite additions
New regression coverage added in this session covers:
- bounded market-queue coalescing
- liquidation preservation under pressure
- systemic classification of `connection_closed:1006`
- external bootstrap failure isolation
- reconnect loops not duplicating supplemental workers
- runtime snapshot exposure of overload counters

## 9) What did *not* change
The repair deliberately did **not** remove or disable the core trading stack:
- strategy selection
- veto framework
- risk logic
- TP/SL behavior
- leverage handling
- cross-venue freshness / alias logic
- health / metrics endpoints
- Telegram formatting
- backtesting modules
