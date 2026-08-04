# PRODUCTION_READINESS.md

## Status: CONDITIONAL PASS — pending live soak on the target VPS

This build closes every P0/P1 production blocker identified in the institutional
audit and the project's own failing pre-fix soak. It is shipped as
`FINAL_PRODUCTION.zip`. Read this file together with `FINAL_VERIFIED.md`,
`ROOT_CAUSE_REPORT.md`, `PERFORMANCE_REPORT.md`, and `SOAK_TEST_RESULTS.md`.

## What is now production-grade

- **Hot path is O(1)/O(window), not O(history).** The CPU/RSS driver behind the
  pre-fix monotone loop-lag climb and RSS growth is removed.
- **Risk safety is fail-closed.** Degenerate signals are rejected before sizing;
  the kill switch and consecutive-loss counter are a persistent latch that
  survives restart and midnight and requires an explicit operator reset.
- **Operator controls work.** `/pause`, `/resume`, `/paused`, `/mute`,
  `/status`, `/stats`, `/reset` (kill switch) are wired to a shared
  `OperatorState` that the live signal engine actually reads.
- **Boot/restart is crash-safe.** Atomic checkpoint writes + tolerant load;
  WAL SQLite with busy_timeout; corrupt persisted state degrades gracefully
  instead of crashing startup.
- **Shutdown is graceful.** SIGINT/SIGTERM handlers trigger a full `stop()`.
- **Ops surface is private.** `/health` + `/metrics` bind `127.0.0.1` by default
  with a bounded, timed request parser.
- **Secrets are not committed** and are redacted in logs and exceptions.

## What is NOT yet production-grade (honest)

1. A **live** 60s smoke + 15m and multi-hour live exchange soak on the
   deployment VPS. This build's soak is synthetic (real app path, no network).
2. **Loop-lag p95 < 250 ms** measured against the real exchange feed.
3. **24h+ RSS plateau** confirmed live (the driver is removed; the multi-day
   confirmation is the final real-money gate).

## Deployment checklist before real money

- [ ] Run `python -m pytest -q` on the VPS (expect 111 passed).
- [ ] `pip install -r requirements.txt` (live runtime only).
- [ ] Set secrets via env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
      `TELEGRAM_ADMIN_CHAT_ID`, `FRED_API_KEY`, `ETHERSCAN_API_KEY`.
- [ ] Keep `ops.bind_host = "127.0.0.1"` unless you intentionally expose the
      ops port on a private LAN (then front it with auth/TLS).
- [ ] Run under a supervisor (systemd unit with `Restart=on-failure`); the
      process now handles SIGTERM cleanly.
- [ ] `run_live_smoke_60s.py` → PASS.
- [ ] `run_live_soak_15m.py` → PASS (flat RSS, loop-lag p95 < 250 ms,
      0 exceptions, 0 drops).
- [ ] Optional: 24h soak before enabling live signals.

Only after the live soak passes: this build is real-money ready.
