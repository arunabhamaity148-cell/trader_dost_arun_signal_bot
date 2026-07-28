# SOAK TEST RESULTS

## 15-minute full-watchlist soak
Executed against public market data with the default full watchlist and no private API keys.

Command:
- `python3 run_live_soak_15m.py`

## Result
**FAIL acceptance**

The soak completed and produced checkpoints at 5, 10, and 15 minutes, but the resulting operating profile does not satisfy the full production-readiness bar.

## Checkpoint metrics

### 5 minutes
- events: **67092**
- events/sec: **219.93**
- reconnects: **{}**
- queue HWM: **742**
- queue depth: **26**
- coalesced snapshots: **86727**
- dropped events: **0**
- stale snapshot suppressions: **1130**
- event-loop lag p95 / max: **657.37 ms / 836.97 ms**
- RSS: **273.26 MB**
- tasks / peak: **57 / 65**

### 10 minutes
- events: **113369**
- events/sec: **186.99**
- reconnects: **{'hyperliquid': 1, 'deribit': 1}**
- queue HWM: **1173**
- queue depth: **30**
- coalesced snapshots: **197310**
- dropped events: **0**
- stale snapshot suppressions: **2447**
- event-loop lag p95 / max: **998.32 ms / 1228.28 ms**
- RSS: **320.70 MB**
- tasks / peak: **64 / 70**

### 15 minutes / final
- events: **159461**
- events/sec: **175.68**
- reconnects: **{'hyperliquid': 1, 'deribit': 1}**
- queue HWM: **1203**
- queue depth: **86**
- coalesced snapshots: **313733**
- dropped events: **0**
- stale snapshot suppressions: **4634**
- event-loop lag p95 / max: **1232.78 ms / 1669.93 ms**
- RSS: **354.91 MB**
- tasks / peak: **63 / 70**
- final health state: **degraded**
- network degraded state: **healthy**
- unexpected exceptions: **[]**

## Reconnect details captured
- Hyperliquid group-2: **heartbeat_timeout**, uptime **329.13s**, last message age **42.85s**, recovered with bounded backoff
- Deribit group-1: **connection_closed:1000**, uptime **602.25s**, recovered with bounded backoff

## Interpretation
What passed:
- soak completed without queue saturation
- no reconnect storm occurred
- dropped events remained at zero
- network degradation logic did not cascade into a global failure
- no unexpected exceptions were recorded

Why acceptance still fails:
- a heartbeat-timeout reconnect still occurred in the soak
- stale-snapshot suppressions remained high
- event-loop lag rose materially over time
- RSS continued rising across the soak rather than clearly plateauing
- final health state ended **degraded**

## Conclusion
The longer run is materially better than the failure profile described in the request, but not strong enough to label fully production-ready.
