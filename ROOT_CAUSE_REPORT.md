# ROOT CAUSE REPORT

## STATUS
**PROVEN:** the uploaded ZIP already contained several resilience fixes (core-vs-enrichment freshness separation, REST retry/circuit-breaker scaffolding, secret redaction, bounded state deques, reconnect telemetry, idempotent shutdown tests).

**PROVEN:** the uploaded ZIP still lacked the required bounded grouped websocket ownership. `ConnectorManager` instantiated one connector task per venue+symbol feed, which means the default watchlist still expanded to 42 websocket tasks instead of a bounded grouped topology.

**PROVEN:** the uploaded ZIP also still lacked grouped supplemental ownership. Binance/OKX/Hyperliquid/Deribit enrichment remained connector-local/per-symbol rather than explicit grouped ownership.

**PROVEN:** SentenceTransformer progress output was not explicitly disabled in production. NewsGuard semantic merge work was still executed inline in the async refresh path.

**PROVEN:** logging used a queue listener, but the queue itself was unbounded (`queue.SimpleQueue`), leaving an avoidable RAM-leak vector under sustained log pressure.

**PROVEN:** the post-repair runtime profile is still not production-ready on the full default watchlist in this sandbox. The 60-second live smoke with the full grouped watchlist hit queue saturation (`queue_depth=5000/5000`) and showed very high event-loop/evaluation lag, so the final classification cannot be production-ready.

## WHAT WAS REPAIRED IN THIS SESSION

### 1) Venue-grouped websocket topology
- Replaced one-task-per-symbol manager ownership with bounded grouped venue connectors.
- Default grouped topology is now:
  - Binance: 2 groups
  - Bybit: 2 groups
  - OKX: 2 groups
  - Hyperliquid: 2 groups
  - Deribit: 1 group
- Group topology is configurable through `max_symbols_per_connection`.

### 2) Grouped supplemental ownership
- Binance open interest polling moved under grouped connector ownership.
- OKX open interest polling moved under grouped connector ownership.
- Hyperliquid asset-context polling is grouped and fan-outs one shared payload to symbols in the group.
- Deribit option metrics polling is grouped by connector/currency ownership.

### 3) Bounded queueing / observability hardening
- Market queue is now explicitly bounded.
- Logging queue is now explicitly bounded with oldest-record drop behavior and queue diagnostics.
- Runtime snapshots now expose topology, queue capacity/depth, logging queue health, RSS, and cache sizes.

### 4) CPU-path hardening
- SentenceTransformer now uses `show_progress_bar=False`.
- Semantic similarity uses an explicit bounded LRU-style cache.
- NewsGuard event merges are moved off the main async path with `asyncio.to_thread(...)` and serialized to avoid concurrent dict mutation.

### 5) Logging noise reduction
- Added suppression-summary aggregation instead of per-event spam for repetitive vetoes.
- Reconnect logs remain actionable and structured.

### 6) Regression coverage added
- Added grouped-topology, grouped-routing, bounded logging queue, runtime topology snapshot, and progress-bar regression tests.
- Full pytest moved from **81 passed** baseline to **88 passed** after this session.

## STILL NOT FULLY VERIFIED
- **PROVEN:** full pytest green.
- **PROVEN:** checkpoint ZIP created and validated.
- **PROVEN:** 60-second full-watchlist live smoke executed.
- **NOT VERIFIED:** 15-minute full configured watchlist soak (not completed in this sandbox workflow).
- **NOT VERIFIED:** clean-room fresh venv install.

## FINAL CLASSIFICATION
Because the 60-second full-watchlist smoke saturated the bounded queue and showed excessive event-loop lag, the repository is delivered as:

**NOT READY**
