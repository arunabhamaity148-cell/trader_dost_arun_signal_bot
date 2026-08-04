# ROOT CAUSE REPORT — production blockers fixed in this build

Every defect below is identified with the file:line of the pre-fix source and the fix that closes it.

## R1. O(history) full-history rebuild on the market hot path (event-loop lag + RSS climb)
- **Where:** `MarketStateStore.view()` copied 8 full slices per call (`trader_dost_arun/core/state.py`) and `spread_percentile()/same_side_depth_percentile()` sorted the full history every call.
- **Root cause:** recomputing closes/highs/lows/volumes/oi... from the full deque on every event. On a 3000-depth buffer this is ~18ms per call plus thousands of object allocations, triggering GC pressure and loop lag.
- **Fix:** maintain a per-(venue:symbol) `KeyedSeries` (bounded rolling windows + running trade_delta200/vwap/ofi caches) updated O(1) on `add_*`. `compute_features` consumes it directly.
  - `view()` 17.9ms → 0.30ms; percentile pair 8.2ms → 1.5ms; `compute_features` ~37ms → ~6.5ms.
  - `_zscore()` switched from Python `statistics.pstdev` (exact rational math) to numpy → big win on 1000+ samples.
  - `atr()` used to scan the full history; now reads only the last (window+2) bars.
  - `app._build_feature_inputs` previously built a full FeatureSet for **every peer**; it now builds the own-side FeatureSet fully and a minimal FeatureSet for each peer (premium/delta_oi), switching the previous ~154ms down to ~4.35ms.

## R2. Kill-switch/daily-loss state lost across restart or midnight
- **Where:** `RiskEngine.restore_state()` discarded the previous day's kill_switch/consecutive_losses, and `maybe_reset()` cleared the latch at the UTC boundary.
- **Fix:** the latch is restored unconditionally from the checkpoint; only the day-scoped cumulative fields (`daily_realized_r`/`daily_slippage_cost`) reset at the day boundary. New `reset_kill_switch()` is the only operator-cleared path. Tests prove the latch survives a simulated midnight.

## R3. Degenerate signals could poison the risk model
- **Where:** `RiskEngine.register_outcome()` divided by `max(risk, 1e-9)`; a `stop == entry` (risk_per_unit == 0) position could be booked as an enormous R loss.
- **Fix:** `register_outcome()` books realized_r = 0 for degenerate positions. `is_valid_signal()` rejects entry<=0, wrong-side stop, no upside/downside target, or degenerate range **before** sizing in `SignalEngine.evaluate()`.

## R4. `pause` / `resume` operator commands were silent no-ops
- **Where:** the Telegram admin bot wrote pause state on its own `TelegramAdminBot.state`; the signal engine consulted `getattr(self.news_guard, "paused_strategies", [])`, which was always empty.
- **Fix:** shared `OperatorState` (`trader_dost_arun/core/operator_state.py`) owns pause/resume/mute, persists atomically, and is injected into both the engine (`SignalEngine(operator_state=...)`) and the admin bot (`TelegramAdminBot(operator_state=...)`). `engine_stats()` feeds `/status` and `/paused`.

## R5. Boot / reload could crash on corrupt persisted state
- **Where:** `StateCheckpoint.load_latest()` blindly parsed `checkpoint.json`; a torn write crashed `SignalEngine.__init__`. `PositionStore.__init__` crashed on a corrupt DB.
- **Fix:** checkpoint writes go to `.tmp` then `os.replace()`; `load_latest()` falls back to `.bak` or `{}` on any parse error. `PositionStore` opens with WAL + busy_timeout and enters a `_degraded` mode on init/read failure instead of raising.

## R6. No graceful shutdown signal handling (SIGTERM)
- **Where:** only SIGINT (Ctrl+C) was handled; a systemd/docker SIGTERM bypassed cleanup.
- **Fix:** `app.py` installs SIGINT/SIGTERM handlers via `loop.add_signal_handler` (Windows-safe fallback) so a VPS stop signal triggers `run_forever()`'s full `stop()`.

## R7. Ops HTTP listener exposed on all interfaces with no request limits
- **Where:** `OpsHttpServer.start()` bound `0.0.0.0` and used `reader.readline()` with no cap/timeout.
- **Fix:** default bind is `127.0.0.1` (`ops.bind_host` overridable). `_handle()` reads with `readuntil` capped at 4096 bytes and a 5s deadline; writes also time out. `/health` and `/metrics` behavior unchanged.

## R8. Telegram send rebuilt an AsyncClient per attempt
- **Where:** `TelegramAlerter.send()` created `httpx.AsyncClient(timeout=10)` inside every attempt loop (TLS handshake per send).
- **Fix:** single pooled client (`_get_client`) with an explicit `aclose()` in `app.stop()`.

## R9. Strategy config KeyError if a strategy is removed from YAML
- **Where:** `deterministic.py` read `config["strategies"][name][key]` directly and raised KeyError for any missing strategy (e.g. after commenting out a strategy section).
- **Fix:** `_strat_cfg(name)` returns `{}` for a missing strategy; every read now uses `.get(key, default)` with documented defaults.

## R10. Model leverage vs displayed leverage could disagree
- **Where:** `SignalEngine` used `metadata.get("leverage", 1.0)` while the alert template computed its own leverage from `stop_pct` — two different numbers could ship in the same message.
- **Fix:** shared `advisory_leverage(signal)` helper is the single source; `SignalEngine` writes it into `signal.metadata["leverage"]` and `TelegramAlerter` uses the same function.

## R11. HMM `_fit_task` double-consume/assert under concurrent `observe`
- **Where:** two awaited calls could both see the done `_fit_task`; the second would hit `assert self._fit_task is not None` after the first set it to `None`.
- **Fix:** `_fit_lock` around the consume path; returns cleanly when the reference is already cleared. `close()` cancels outstanding fits on shutdown.

## R12. Add/remove position while iterating (exposure correctness under scheduler concurrency)
- **Where:** `ExposureOptimizer.evaluate()` iterated `self.positions` while `update_open_positions()` (`_close_position_async` / `add_position_async`) rebased it on another task; `SignalEngine.update_open_positions()` also mutated `performances` from the market-consumer while the evaluator read it.
- **Fix:** reads use `open_positions_snapshot()`; mutations happen under an asyncio Lock. SQLite persistence moved to `asyncio.to_thread` so signal evaluation never blocks on disk.

## R13. Dead/incorrect LLM glue
- **Where:** `newsguard/llm_classifier.py` was unreferenced (subprocess + SQLite + GLM) with a test that monkeypatched `subprocess.run`.
- **Fix:** removed (module + test). `NewsGuard.assess()` remains heuristic-only.

## R14. Config validation was absent
- **Fix:** `load_settings()` now calls `validate_config(config)` and raises at startup with the offending key if a required section/key/numeric bound is missing/invalid (was previously a 3AM runtime failure).

## R15. `/mute` parser crash on non-numeric input
- **Where:** `int(parts[1])` would throw, killing the admin poll loop.
- **Fix:** parser tolerates bad numerics and returns a `Usage:` hint.

## Verification of fixes
- All 111 unit/integration tests pass (was 113 before removing the 3 dead-LLM tests).
- Full hot-path profiling against the pre-fix baseline shows the dominant per-event work items reduced by an order of magnitude (see RUNTIME_VERIFICATION.md and TEST_RESULTS.md).
- `run_soak_synthetic.py` (60s, 400 events/sec on the full 5x10 watchlist) shows flat RSS (≈180MB), bounded queue HWM (≈448/5000), zero exceptions, and graceful SIGTERM shutdown — see SOAK_TEST_RESULTS.md.
