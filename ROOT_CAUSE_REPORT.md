# ROOT CAUSE REPORT

## Final status
**REPAIRED — PARTIALLY VERIFIED**

The supplied ZIP already contained grouped websocket connectors, retry scaffolding, bounded state deques, and a substantial regression suite. The remaining production-hardening work in this session focused on the live-failure classes described in the request and validated them against fresh pytest, clean-install, live smoke, and a 15-minute full-watchlist soak.

## Root causes addressed

### 1) Market-queue backpressure could starve websocket readers
The prior build used a plain bounded `asyncio.Queue` for all market events. Under bursty grouped feeds this meant websocket tasks could block on `await queue.put(...)` behind obsolete snapshots. That creates a credible shared-cause path for synchronized disconnects across unrelated venues: readers stop draining live feeds, server-side buffers fill, and connections close even though the last successfully processed message was recent.

**Fix applied:** replaced the plain queue in connector-manager ownership with a bounded market-ingress queue that coalesces snapshots by `venue:symbol`, preserves latest-state semantics, keeps critical events bounded, and exposes overload counters.

### 2) Heartbeat ownership was split between library keepalives and application liveness probes
The connectors were using websocket-library auto-pings while also running application-owned recv-timeout + ping probing. That is avoidable ambiguity in heartbeat ownership and makes troubleshooting disconnects harder.

**Fix applied:** disabled websocket-library auto-pings for connector sockets and kept the application-owned recv-timeout / probe path as the explicit liveness owner.

### 3) Abnormal disconnects were under-classified for systemic network coordination
Transport failures participated in network-degraded coordination, but disconnect classes such as heartbeat timeouts and abnormal websocket closures were not fed into the same coordination path.

**Fix applied:** systemic-failure classification now includes `heartbeat_timeout` and abnormal `connection_closed:10xx` close reasons so global degradation logic can coordinate reconnect pressure when several venues fail together.

### 4) External-context failures had weak bootstrap isolation and poor diagnostics
External context refresh could fail noisily without useful component attribution, and bootstrap failures could bubble during startup.

**Fix applied:** component-level isolation/logging was added for external context refresh, bootstrap failure is degraded instead of fatal, and cooldown/backoff state is retained inside the external-context client.

### 5) Telegram disabled-state logging was duplicated
Disabled Telegram status was emitted by more than one component.

**Fix applied:** disabled-state reporting is centralized at application startup and the admin-bot component now silently no-ops when not configured.

### 6) RSS telemetry was Linux-only and could report `0.00`
The previous implementation relied only on `/proc/self/status`, which is unavailable on Windows.

**Fix applied:** RSS measurement now uses `/proc/self/status` on Linux, `GetProcessMemoryInfo` on Windows, and `resource.getrusage(...)` as a compatible fallback where available.

## What the new evidence showed

### Confirmed improvements
- 60-second full-watchlist run stayed bounded at **9 sockets** with **0 reconnects**, **0 unexpected exceptions**, **queue HWM 722 / 5000**, and **0 dropped events**.
- Snapshot coalescing was active in live trading flow (`coalesced_snapshots=10610` in the 60-second run) while the queue never saturated.
- Full regression suite expanded to **95 passed**.
- Clean install in a fresh virtualenv passed with **95/95 tests**.

### Remaining operational limitations
The 15-minute full-watchlist soak completed, but acceptance still failed:
- one **Hyperliquid heartbeat timeout** reconnect occurred
- one **Deribit normal 1000 close** reconnect occurred
- final health status was **degraded**
- stale-snapshot suppressions rose to **4634**
- event-loop lag reached **p95 1232.78 ms / max 1669.93 ms**
- RSS continued rising from **273.26 MB → 320.70 MB → 354.91 MB** over the soak rather than clearly plateauing

## Conclusion
The key stability fixes were implemented and materially improved the runtime profile versus the failure pattern described in the request. However, the completed 15-minute soak still shows enough operational pressure that calling this build fully production-ready would be overstated.

**Final classification: REPAIRED — PARTIALLY VERIFIED**
