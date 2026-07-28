# ARCHITECTURE CHANGES

## 1. Connector ownership model

### Before
- `ConnectorManager` created one websocket task per `venue:symbol`.
- Default watchlist expanded to ~42 websocket tasks.
- Supplemental REST enrichment ownership also lived per symbol.

### After
- `ConnectorManager` now groups symbols per venue and starts one grouped connector task per bounded symbol batch.
- Default topology:
  - Binance: 2 grouped connectors (5 symbols each)
  - Bybit: 2 grouped connectors (5 symbols each)
  - OKX: 2 grouped connectors (5 symbols each)
  - Hyperliquid: 2 grouped connectors (5 symbols each)
  - Deribit: 1 grouped connector (2 symbols)
- Effective default websocket count: **9**.

## 2. New grouped connector layer
Added `trader_dost_arun/data/grouped.py` containing grouped venue connectors:
- `BinanceGroupedConnector`
- `BybitGroupedConnector`
- `OkxGroupedConnector`
- `HyperliquidGroupedConnector`
- `DeribitGroupedConnector`

Each grouped connector provides:
- bounded symbol ownership
- per-symbol cache/state inside a shared connection owner
- grouped subscriptions
- grouped supplemental polling ownership
- per-symbol routing from shared payload streams
- stop-aware reconnect behavior inherited from the base connector logic

## 3. Supplemental polling changes
- Binance: grouped open-interest polling loop iterates symbols under one connector owner.
- OKX: grouped open-interest polling loop iterates symbols under one connector owner.
- Hyperliquid: one grouped `metaAndAssetCtxs` poll fans out to all symbols in the connector.
- Deribit: grouped option-metrics polling fans out by currency-owned connector group.

## 4. Runtime observability additions
`TradingApplication.runtime_snapshot()` now exposes:
- grouped topology
- queue capacity / depth / HWM
- logging queue status
- RSS / RSS peak
- cache sizes
- state sizes

`/health` now carries the same operational signals.

## 5. Logging pipeline hardening
- Replaced unbounded `SimpleQueue` with bounded `queue.Queue(maxsize=10000)`.
- Added oldest-record drop behavior for queue overflow.
- Added queue snapshot reporting (`queue_depth`, `queue_capacity`, `dropped_records`).
- Added suppression-summary aggregation.

## 6. NewsGuard / embedding path hardening
- SentenceTransformer progress output disabled explicitly.
- Similarity cache bounded.
- NewsGuard semantic merge work moved to `asyncio.to_thread(...)`.
- Added serialization around merge mutation to prevent concurrent dict modification.
- Added event-retention pruning.

## 7. Current limitation after repair
The architecture is materially improved and fully unit-tested, but the full default-watchlist live smoke still showed queue saturation and high event-loop lag in this sandbox. The system is therefore repaired but not production-ready from the evidence collected here.
