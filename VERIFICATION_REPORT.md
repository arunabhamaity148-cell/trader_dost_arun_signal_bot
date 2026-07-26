# VERIFICATION REPORT

## 1) Pytest
```text
................................................                         [100%]
=============================== warnings summary ===============================
tests/test_persistence.py::test_close_position_updates_history
tests/test_signal_engine_outcomes.py::test_position_monitor_updates_learning_components
  /home/user/downloads/trader_fix/trader_dost_arun_signal_bot-main/trader_dost_arun/core/persistence.py:118: DeprecationWarning:
  
  datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
48 passed, 2 warnings in 2.18s
```

## 2) 60-second bot run with empty `.env`
### Connected venues observed
```text
binance
bybit
deribit
hyperliquid
okx
```

### Last 30 log lines
```text
2026-07-24 12:27:58,509 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.4s, reconnects=0
2026-07-24 12:27:58,513 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.4s, reconnects=0
2026-07-24 12:27:58,518 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,522 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,526 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,530 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,534 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,538 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,542 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,547 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,551 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,555 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,560 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,564 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,568 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,572 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,577 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,581 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,585 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,589 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,594 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,598 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,603 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,607 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,612 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,616 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.5s, reconnects=0
2026-07-24 12:27:58,620 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.6s, reconnects=0
2026-07-24 12:27:58,625 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.6s, reconnects=0
2026-07-24 12:27:58,629 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.6s, reconnects=0
2026-07-24 12:27:58,634 INFO trader_dost_arun.ops.alerts telegram disabled: ⚠️ <b>Health warning</b> bybit: score=30.0, p95=8549.4ms, stale=45.6s, reconnects=0
```

### Grep confirmation for banned log tokens
```text
No Traceback / AttributeError / KeyError / CRITICAL found in app_run.log
```

## 3) /metrics response while bot was running
```text
# HELP python_gc_objects_collected_total Objects collected during gc
# TYPE python_gc_objects_collected_total counter
python_gc_objects_collected_total{generation="0"} 812.0
python_gc_objects_collected_total{generation="1"} 52.0
python_gc_objects_collected_total{generation="2"} 0.0
# HELP python_gc_objects_uncollectable_total Uncollectable objects found during GC
# TYPE python_gc_objects_uncollectable_total counter
python_gc_objects_uncollectable_total{generation="0"} 0.0
python_gc_objects_uncollectable_total{generation="1"} 0.0
python_gc_objects_uncollectable_total{generation="2"} 0.0
# HELP python_gc_collections_total Number of times this generation was collected
# TYPE python_gc_collections_total counter
python_gc_collections_total{generation="0"} 134.0
python_gc_collections_total{generation="1"} 12.0
python_gc_collections_total{generation="2"} 1.0
# HELP python_info Python platform information
# TYPE python_info gauge
python_info{implementation="CPython",major="3",minor="13",patchlevel="14",version="3.13.14"} 1.0
# HELP process_virtual_memory_bytes Virtual memory size in bytes.
# TYPE process_virtual_memory_bytes gauge
process_virtual_memory_bytes 9.9065856e+08
# HELP process_resident_memory_bytes Resident memory size in bytes.
# TYPE process_resident_memory_bytes gauge
process_resident_memory_bytes 2.67436032e+08
# HELP process_start_time_seconds Start time of the process since unix epoch in seconds.
# TYPE process_start_time_seconds gauge
process_start_time_seconds 1.78489601815e+09
# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.
# TYPE process_cpu_seconds_total counter
process_cpu_seconds_total 2.21
# HELP process_open_fds Number of open file descriptors.
# TYPE process_open_fds gauge
process_open_fds 86.0
# HELP process_max_fds Maximum number of open file descriptors.
# TYPE process_max_fds gauge
process_max_fds 1024.0
# HELP signals_total Signals emitted
# TYPE signals_total counter
signals_total 0.0
# HELP signals_created Signals emitted
# TYPE signals_created gauge
signals_created 1.7848960197808013e+09
# HELP signal_veto_total Signals vetoed
# TYPE signal_veto_total counter
# HELP signal_latency_seconds Signal evaluation latency
# TYPE signal_latency_seconds histogram
signal_latency_seconds_bucket{le="0.005"} 0.0
signal_latency_seconds_bucket{le="0.01"} 0.0
signal_latency_seconds_bucket{le="0.025"} 0.0
signal_latency_seconds_bucket{le="0.05"} 0.0
signal_latency_seconds_bucket{le="0.075"} 0.0
signal_latency_seconds_bucket{le="0.1"} 0.0
signal_latency_seconds_bucket{le="0.25"} 0.0
signal_latency_seconds_bucket{le="0.5"} 0.0
signal_latency_seconds_bucket{le="0.75"} 0.0
signal_latency_seconds_bucket{le="1.0"} 0.0
signal_latency_seconds_bucket{le="2.5"} 0.0
signal_latency_seconds_bucket{le="5.0"} 0.0
signal_latency_seconds_bucket{le="7.5"} 0.0
signal_latency_seconds_bucket{le="10.0"} 0.0
signal_latency_seconds_bucket{le="+Inf"} 0.0
signal_latency_seconds_count 0.0
signal_latency_seconds_sum 0.0
# HELP signal_latency_seconds_created Signal evaluation latency
# TYPE signal_latency_seconds_created gauge
signal_latency_seconds_created 1.784896019780844e+09
```

## 4) /health response while bot was running
```text
{"status": "ok"}
```

## 5) Backtest HTML verification
- HTML path: `data/backtest_reports/2026-07-24_122847.html`
- Plotly confirmation: **plotly-graph-div present**

## 6) Telegram formatter sample output
```text
━━━━━━━━━━━━━━━━━━━
💎 <b>ELITE SIGNAL</b> · #1
━━━━━━━━━━━━━━━━━━━
🟢 <b>BTCUSDT</b> · <b>BINANCE</b> · <b>LONG</b>
🎯 <b>Liquidation Cascade Continuation</b>
📊 <b>SETUP QUALITY</b>
┌─────────────────────────┐
│ Confluence Score: 8/10  │
│ ████████░░ 78.4%          │
│ Regime: 📈 Trending      │
│ Regime Weight: 1.22x ▲  │
└─────────────────────────┘
💰 <b>TRADE PLAN</b>
📍 Entry:  <code>67,234.55</code>
🛑 Stop:   <code>66,990.12</code>  (-0.36%)
🎯 TP1:    <code>67,698.45</code>  (+0.69% · 1.9R)
🎯 TP2:    <code>68,162.35</code>  (+1.38% · 3.8R)
🎯 TP3:    <code>68,626.25</code>  (+2.07% · 5.7R)
⚖️  Risk:Reward = <b>1 : 1.90</b>
🧮 <b>POSITION SIZING</b>
┌─────────────────────────┐
│ Kelly Size:    2.40%    │
│ Suggested Cap: 1.50%    │
│ Leverage:      5x       │
│ Margin (1k):   $4.80   │
└─────────────────────────┘
🧠 <b>AI CONFIDENCE</b>
┌─────────────────────────┐
│ Overall:     🟢 78.4%   │
│ Meta-Label:  🟡 67.2%   │
│ Bayesian:    🟢 82.1%   │
│ Calibrated:  🟢 74.8%   │
│ Live Win Rate: 71% (24) │
└─────────────────────────┘
✅ <b>FILTERS PASSED</b>: 21/21
🛡️  Veto Checks: All Clear
📰 NewsGuard: No Active Threats
🐳 Whale Flow: Net +$2.3M (bullish)
🔍 <b>WHY THIS SETUP</b>
• Liquidation cascade detected (z-score 3.2)
• Range breakout confirmed
• Delta OI aligned with direction
• Adverse depth not replenishing
• Microprice leading mid-price
📈 <b>STRUCTURAL CONTEXT</b>
• BOS confirmed (4h timeframe)
• Bullish FVG unfilled below
• Order Block active at entry
• No liquidity sweep against
⏰ <b>TIMING</b>
• Signal Age: 0s
• Valid Window: ~2-5 min
• Cooldown: 8 min after this
• Next Funding: in 23 min
━━━━━━━━━━━━━━━━━━━
⚠️  <i>Not financial advice. Manage your own risk.</i>
━━━━━━━━━━━━━━━━━━━
```
