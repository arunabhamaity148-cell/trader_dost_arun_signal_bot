# RUNTIME VERIFICATION

## Status
**PROVEN:** a live public-market smoke run was executed against the full configured default watchlist after the grouped-connector repair.

**PROVEN:** the grouped websocket topology held at the expected bounded level:
- Binance: 2
- Bybit: 2
- OKX: 2
- Hyperliquid: 2
- Deribit: 1
- Total sockets: **9**

## 60-second full-watchlist live smoke
Command executed:
```bash
python run_live_smoke_60s.py
```

Observed final snapshot:
- Runtime duration: **88.56s** (includes startup/shutdown overhead around the 60s run window)
- Events processed: **43,619**
- Events/sec: **492.52**
- Socket count: **9**
- Queue depth: **5000 / 5000**
- Queue HWM: **4395**
- Reconnect count by venue: **{}**
- Reconnect reasons: **{}**
- Unexpected exceptions: **[]**
- RSS: **252.92 MB**
- RSS peak: **252.92 MB**
- Logging queue: **depth 5 / capacity 10000 / dropped 0**
- Cache sizes: **{'events': 11, 'embedding_similarity_cache': 133, 'market_state_symbols': 42}**
- Healthy snapshot evaluations: **542**
- Signals evaluated: **599**
- Signals emitted: **0**
- Stale snapshot suppressions: **87**
- Evaluation latency p95 / max: **1910.26 ms / 16027.93 ms**
- Event-loop lag p95 / max: **4072.50 ms / 18497.97 ms**

## Interpretation
### What passed
- Grouped topology stayed bounded at **9** sockets.
- No reconnect waves were observed during this smoke.
- No unexpected exceptions were recorded.
- Optional enrichment failures (for example Binance HTTP 451 on open-interest polling) remained isolated from websocket ingestion.
- Logging queue remained bounded and did not drop records during the smoke.

### What failed
- The bounded market queue saturated to its full configured capacity (`5000/5000`).
- Event-loop lag and evaluation latency were too high for a production-ready full-watchlist profile in this sandbox run.
- Because the queue saturated, this smoke **does not qualify as a production pass**.

## Reconnect / heartbeat summary
- Heartbeat/reconnect instability did **not** reproduce in this smoke.
- No `1006` reconnect wave evidence was recorded in the collected snapshot.
- This is positive evidence, but insufficient to override the queue/lag failure.

## Shutdown
**PARTIALLY VERIFIED**

The application completed startup and stop without runtime snapshot exceptions and without unexpected exceptions in the smoke snapshot. However, no separate extended shutdown torture run was executed beyond the unit/regression coverage already in pytest.

## Final runtime classification
Because the grouped topology objective was met but the full-watchlist smoke saturated the queue and showed severe lag, the runtime result is:

**NOT READY**
