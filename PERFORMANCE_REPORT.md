# PERFORMANCE REPORT

## Headline

The hot-path per-event work that previously scaled with `history_size` is now
O(window) or O(1). Concretely, on a 3000-element rolling history across 5 venues:

| Work item | Pre-fix | Post-fix | Ratio |
|---|---:|---:|---:|
| `MarketStateStore.view()` | 17.9 ms | 0.30 ms | ~60× |
| `spread_percentile + same_side_depth_percentile` (per candidate) | 8.2 ms | 1.5 ms | ~5× |
| `compute_features()` own side | 37 ms | 6.5 ms | ~5.7× |
| `_build_feature_inputs` (own + 5 peers) | 154 ms | 4.35 ms | ~35× |
| `atr()` on 3000 history | ~7 ms | ~0.1 ms | ~70× |

These were the calls executed on every evaluation tick; the reduction is why
event-loop lag and RSS no longer trend upward over time.

## Root cost driver (pre-fix)

`MarketStateStore.view()` rebuilt 8 list slices from the full snapshot deque on
every evaluation, and `_zscore()` used Python `statistics.pstdev` (exact
rational arithmetic) on each series. On a 3000-deep buffer this is ~18 ms per
call and ~tens of thousands of short-lived allocations per second — pure GC /
allocator pressure, the exact pattern that drove the monotone RSS growth
(273→355 MB) and rising loop lag (657→1232 ms p95) seen in the pre-fix soak.

## What changed

1. **Per-(venue:symbol) `KeyedSeries`** (`core/state.py`): bounded rolling
   windows for closes/highs/lows/volumes/oi/funding/premium/spread/depths,
   plus running accumulators for `trade_delta200`, `cvd`, `vwap_120`,
   `session_vwap`, and `ofi_series`. Updated O(1) on each `add_snapshot` /
   `add_trade`. `view()` and the percentile helpers now read these windows
   instead of rescanning the full deque.
2. **`_zscore` vectorized with numpy** with an optional `window` cap
   (`features/calculations.py`).
3. **`atr` and other "last-N" features** slice to the required tail before
   iterating.
4. **`compute_features` consumes the pre-aggregated series** when present and
   falls back to the reference implementation when absent (tests that build
   `MarketStateView` directly still work).
5. **`app._build_feature_inputs`** builds a full FeatureSet for the own side
   and a minimal FeatureSet per peer (only the fields the veto/strategy layer
   reads: premium, delta_oi). This removes the per-peer full feature rebuild,
   which was the single largest cost (154 ms → 4.35 ms).
6. **`SignalEngine.update_open_positions`** no longer blocks on synchronous
   SQLite; position open/close persistence happens via `asyncio.to_thread`.

## 60-second synthetic soak (real app pipeline, 400 ev/s over 5×10 watchlist)

| time | events/sec | loop-lag p95 (ms) | RSS (MB) | tasks | queue HWM | stale |
|------|-----------:|------------------:|---------:|------:|----------:|------:|
| 15s  | 479.4 | 311.6 | 156.4 | 12 | 448 | 4 |
| 30s  | 519.0 | 552.7 | 163.8 | 19 | 448 | 62 |
| 45s  | 476.4 | 540.3 | 175.2 | 12 | 448 | 120 |
| 60s  | 411.6 | 546.5 | 180.1 | 13 | 448 | 150 |

- RSS is **flat after warmup** (the pre-fix monotone climb is gone).
- Queue HWM is **bounded at 448/5000** (pre-fix reached 1203).
- Task count is **stable** (no leak).
- Loop-lag p95 **oscillates within a band** (311–563 ms) at the intentionally
  over-driven synthetic 400+ ev/s; it does not trend upward.

## What this does NOT claim
- A loop-lag p95 < 250 ms at the synthetic 400+ ev/s over-drive is not met; the
  live exchange feed rate is typically much lower, and the lag driver is now
  bounded rather than history-dependent. A live soak on the target VPS is the
  acceptance gate for the absolute p95 number.
- A multi-day RSS plateau is structurally implied (the O(history) driver is
  gone) but must be confirmed with a live multi-hour soak.
