# RUNTIME VERIFICATION

## 60-second full-watchlist smoke
Executed against public market data with the default full watchlist and no private API keys.

Command:
- `python3 run_live_smoke_60s.py`

## Result
**PASS for short smoke stability**

Measured final snapshot:
- duration: **65.12s**
- events: **23694**
- events/sec: **363.87**
- socket count: **9**
- reconnects by venue: **{}**
- reconnect reason distribution: **{}**
- 1006 closures: **0**
- heartbeat timeouts: **0**
- queue depth: **30 / 5000**
- queue high-water mark: **722**
- coalesced snapshots: **10610**
- dropped events: **0**
- unexpected exceptions: **[]**
- event-loop lag p95 / max: **260.02 ms / 308.00 ms**
- evaluation latency p95 / max: **226.00 ms / 324.43 ms**
- RSS end / peak: **219.55 MB / 219.55 MB**
- logging queue dropped records: **0**
- stale snapshot suppressions: **26**
- network state: **healthy**

## Observations
What improved materially:
- grouped topology stayed bounded at the intended **9 sockets**
- no cross-venue reconnect storm reproduced
- no queue saturation occurred
- snapshot coalescing was active and prevented stale book buildup
- REST enrichment failures (Binance 451) remained isolated from websocket ingestion
- no unexpected exceptions were recorded

What still matters:
- the smoke was good enough to proceed to a longer soak, but it is not sufficient on its own to claim production readiness

## Acceptance outcome for this stage
- grouped topology bounded: **PASS**
- synchronized reconnect storm absent: **PASS**
- queue saturation absent: **PASS**
- processing kept up for 60 seconds: **PASS**
- RSS telemetry working: **PASS**
- core runtime exceptions absent: **PASS**
