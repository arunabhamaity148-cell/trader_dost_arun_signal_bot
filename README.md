# 🤖 Trader Dost Arun — Elite Signal Bot v2 (বাংলা গাইড)

> একটি প্রোডাকশন-গ্রেড ক্রিপ্টো ফিউচারস সিগন্যাল বট। ৫টি এক্সচেঞ্জ থেকে লাইভ ডেটা স্ক্যান করে, ১৯টি স্ট্র্যাটেজি চালায়, ২১টি ভিটো ফিল্টার দিয়ে যাচাই করে, HMM রেজিম ডিটেকশন, Bayesian কনফিডেন্স, LightGBM মেটা-লেবেল ML, Kelly সাইজিং, এবং আল্ট্রা-প্রিমিয়াম টেলিগ্রাম মেসেজ দেয়।

---

## 📑 সূচিপত্র

1. [এক নজরে বট](#-এক-নজরে-বট)
2. [Telegram সিগন্যাল কেমন দেখায়](#-telegram-সিগন্যাল-কেমন-দেখায়)
3. [Telegram Bot Commands](#-telegram-bot-commands)
4. [ফাইল স্ট্রাকচার](#-ফাইল-স্ট্রাকচার)
5. [বট কীভাবে স্ক্যান করে](#-বট-কীভাবে-স্ক্যান-করে)
6. [১৯টি স্ট্র্যাটেজি](#-১৯টি-স্ট্র্যাটেজি)
7. [২১টি ভিটো ফিল্টার](#-২১টি-ভিটো-ফিল্টার)
8. [অ্যাডাপ্টিভ লেয়ার](#-অ্যাডাপ্টিভ-লেয়ার)
9. [রিস্ক ম্যানেজমেন্ট](#-রিস্ক-ম্যানেজমেন্ট)
10. [Backtest করা](#-backtest-করা)
11. [ইনস্টল ও রান](#-ইনস্টল-ও-রান)
12. [কনফিগারেশন](#-কনফিগারেশন)
13. [Observability](#-observability)
14. [FAQ](#-faq)
15. [ডিসক্লেইমার](#-ডিসক্লেইমার)

---

## 🚀 এক নজরে বট

| দিক | বিবরণ |
|-----|--------|
| এক্সচেঞ্জ | Binance, Bybit, OKX, Hyperliquid, Deribit |
| কয়েন | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, ARB |
| স্ট্র্যাটেজি | ১৯টি (Continuation + Reversion + Carry/Arb + Whale) |
| ভিটো ফিল্টার | ২১টি (নিরাপত্তা গেট) |
| রেজিম ডিটেকশন | HMM (500 samples + BIC + KL drift) |
| মেটা-লেবেল ML | LightGBM + SHAP + Isotonic calibration |
| Bayesian কনফিডেন্স | Beta-Binomial + hierarchical shrinkage |
| পজিশন সাইজিং | Kelly Criterion (3% cap, half-Kelly) |
| NewsGuard | LLM (GLM-4.6) + 6 source (RSS/X/Telegram/Whale) |
| Whale Tracker | ETH + BTC + TRON + SOL (4 chain) |
| Position Persistence | SQLite-backed (crash-safe) |
| Slippage Model | Realistic / Conservative / Aggressive |
| Backtest Engine | Event-driven + Plotly equity curves |
| Observability | Prometheus /metrics + /health + structured JSON logs |
| Risk Engine | Kill switch + daily loss limit + cooldown + RR validation |
| Telegram UX | Ultra-premium template + admin bot (/mute /status /stats) |
| টেস্ট কভারেজ | 48 tests (0 failures) |

> ⚠️ এটি শুধু সিগন্যাল বট — নিজে কোনো ট্রেড করে না। সিগন্যাল পেলে আপনি নিজে ম্যানুয়ালি ট্রেড নেবেন।

---

## 📲 Telegram সিগন্যাল কেমন দেখায়

বট যখন কোনো সিগন্যাল ফায়ার করে, টেলিগ্রামে নিচের মতো মেসেজ আসে (এটি BNB LONG-এর আসল উদাহরণ):

```
━━━━━━━━━━━━━━━━━━━
💎 ELITE SIGNAL · #1
━━━━━━━━━━━━━━━━━━━
🟢 BNBUSDT · BINANCE · LONG
🎯 Fresh Oi Breakout Continuation
📊 SETUP QUALITY
┌─────────────────────────┐
│ Confluence Score: 9/10  │
│ ████████░░ 84.2%          │
│ Regime: 📈 Trending      │
│ Regime Weight: 1.22x ▲  │
└─────────────────────────┘
💰 TRADE PLAN
📍 Entry:  598.20
🛑 Stop:   592.40  (-0.97%)
🎯 TP1:    609.50  (+1.89% · 1.9R)
🎯 TP2:    618.80  (+3.44% · 3.6R)
🎯 TP3:    628.10  (+5.00% · 5.2R)
⚖️  Risk:Reward = 1 : 1.95
🧮 POSITION SIZING
┌─────────────────────────┐
│ Kelly Size:    2.65%    │
│ Suggested Cap: 1.50%    │
│ Leverage:      5x       │
│ Margin (1k):   $5.30   │
└─────────────────────────┘
🧠 AI CONFIDENCE
┌─────────────────────────┐
│ Overall:     🟢 84.2%   │
│ Meta-Label:  🟢 76.5%   │
│ Bayesian:    🟢 88.1%   │
│ Calibrated:  🟢 82.4%   │
│ Live Win Rate: 74% (31) │
└─────────────────────────┘
✅ FILTERS PASSED: 21/21
🛡️  Veto Checks: All Clear
🐳 Whale Flow: Net -$5.2M from Binance (bullish)
🔍 WHY THIS SETUP
• Range breakout confirmed (20-bar high broken)
• Fresh OI added (+24,500 contracts)
• Premium widening (not extreme)
• No absorption detected
• Microprice leading mid-price
📈 STRUCTURAL CONTEXT
• BOS confirmed (1h timeframe)
• Bullish FVG unfilled below
• Order Block active at entry
• No liquidity sweep against
⏰ TIMING
• Signal Age: 0s
• Valid Window: ~4-8 min
• Cooldown: 8 min after this
• Next Funding: in 41 min
━━━━━━━━━━━━━━━━━━━
⚠️  Not financial advice. Manage your own risk.
━━━━━━━━━━━━━━━━━━━
```

### 📖 প্রতিটি লাইনের মানে:

| লাইন | মানে |
|------|------|
| `💎 ELITE SIGNAL · #1` | সিগন্যাল নম্বর (SQLite-এ persist করা, বট restart হলেও বাড়বে) |
| `🟢 BNBUSDT · BINANCE · LONG` | সিম্বল + এক্সচেঞ্জ + দিক। 🟢=LONG, 🔴=SHORT |
| `🎯 Fresh Oi Breakout Continuation` | কোন স্ট্র্যাটেজি থেকে সিগন্যাল এসেছে |
| `Confluence Score: 9/10` | ১০ এর মধ্যে কতগুলো কনফারমেশন মিলেছে |
| `██████████░░ 84.2%` | ASCII প্রগ্রেস বার + confidence % |
| `Regime: 📈 Trending` | বর্তমান রেজিম (Trending / Mean Reverting / High Stress / Warmup) |
| `Regime Weight: 1.22x ▲` | এই রেজিমে স্ট্র্যাটেজি ১.২২ গুণ আপ-ওয়েটেড |
| `📍 Entry: 598.20` | এন্ট্রি প্রাইস |
| `🛑 Stop: 592.40 (-0.97%)` | স্টপ লস প্রাইস ও % দূরত্ব |
| `🎯 TP1/TP2/TP3` | ৩টি টেক-প্রফিট লেডার, প্রতিটিতে % ও R মাল্টিপল |
| `⚖️ Risk:Reward = 1 : 1.95` | ১ টাকা রিস্কে ১.৯৫ টাকা লাভের সম্ভাবনা |
| `Kelly Size: 2.65%` | Kelly Criterion দিয়ে সাজেস্টেড পজিশন সাইজ |
| `Suggested Cap: 1.50%` | প্রফেশনাল cap (3% এর নিচে) |
| `Leverage: 5x` | সাজেস্টেড লিভারেজ (max 5x) |
| `Margin (1k): $5.30` | $১০০০ অ্যাকাউন্টে $৫.৩০ মার্জিন লাগবে |
| `Overall Confidence: 🟢 84.2%` | Calibrated সম্পূর্ণ কনফিডেন্স (🟢≥70%, 🟡55-70%, 🔴<55%) |
| `Meta-Label: 🟢 76.5%` | LightGBM ML মডেলের ভবিষ্যৎ সাফল্য সম্ভাবনা |
| `Bayesian: 🟢 88.1%` | Beta-Binomial posterior কনফিডেন্স |
| `Calibrated: 🟢 82.4%` | Isotonic regression দিয়ে calibrated স্কোর |
| `Live Win Rate: 74% (31)` | এই স্ট্র্যাটেজির শেষ ৩১ ট্রেডে ৭৪% উইন রেট |
| `✅ FILTERS PASSED: 21/21` | ২১টি ভিটো ফিল্টারের সব পাস |
| `🛡️ Veto Checks: All Clear` | কোনো ফিল্টার ফেল করেনি |
| `📰 NewsGuard` | (শুধু তখনই দেখায় যখন কোনো active news threat থাকে) |
| `🐳 Whale Flow` | (শুধু তখনই দেখায় যখন বড় whale movement থাকে) |
| `🔍 WHY THIS SETUP` | ৫টি প্রধান কনফারমেশন কারণ |
| `📈 STRUCTURAL CONTEXT` | Smart Money Concepts: BOS, FVG, Order Block, Liquidity Sweep |
| `⏰ TIMING` | Signal age, valid window, cooldown, next funding time |
| `⚠️ Not financial advice` | ডিসক্লেইমার |

### 🚨 Health Alert (যদি কোনো venue খারাপ চলে):

যদি কোনো এক্সচেঞ্জের স্বাস্থ্য খারাপ হয় (score < 60), আলাদা মেসেজ আসে:

```
⚠️ Health warning binance: score=45.3, p95=380.5ms, stale=12.4s, reconnects=3
```

---

## 🤖 Telegram Bot Commands

বটের সাথে একটি admin bot চলে যা নিচের কমান্ড বোঝে (শুধু admin chat ID থেকে):

| কমান্ড | কাজ |
|--------|-----|
| `/mute 60` | ৬০ মিনিটের জন্য সব সিগন্যাল বন্ধ করুন |
| `/pause liquidation_cascade_continuation` | নির্দিষ্ট স্ট্র্যাটেজি পজ করুন |
| `/resume liquidation_cascade_continuation` | পজ করা স্ট্র্যাটেজি আবার চালু করুন |
| `/status` | বর্তমান পজিশন, রেজিম, ডেইলি PnL |
| `/stats` | ৭/৩০ দিনের win rate, profit factor, total R |

### Admin Chat ID সেটআপ:

`.env` ফাইলে:
```
TELEGRAM_ADMIN_CHAT_ID=<আপনার_টেলিগ্রাম_ইউজার_ID>
```

(নিজের user ID জানতে: @userinfobot কে message পাঠান)

---

## 📁 ফাইল স্ট্রাকচার

```
trader_dost_arun_signal_bot_v2_fixed/
│
├── app.py                          # মূল এন্ট্রি পয়েন্ট — এখান থেকে বট চলে
├── README.md                       # এই ফাইল (বাংলা গাইড)
├── CHANGELOG.md                    # সব ফিক্সের তালিকা
├── VERIFICATION_REPORT.md           # pytest + bot run + curl verification
├── requirements.txt                # Python ডিপেন্ডেন্সি
├── .env.example                    # এনভায়রনমেন্ট টেমপ্লেট
├── pytest.ini                      # pytest কনফিগ
│
├── config/
│   ├── defaults.yaml               # সব ডিফল্ট সেটিং
│   └── local.example.yaml          # লোকাল ওভাররাইড নমুনা
│
├── data/                           # SQLite DBs + backtest reports
│   ├── historical.sqlite3          # feature rows + labels (30 দিন)
│   ├── positions.sqlite3           # open/closed positions
│   ├── signal_counter.sqlite3       # signal ID counter
│   ├── news_guard_replay.sqlite3    # news events replay store
│   ├── checkpoint.json              # periodic state snapshot
│   ├── models/                      # ML model artifacts
│   └── backtest_reports/            # HTML + CSV reports
│
├── logs/
│   ├── signal_bot.log               # মূল লগ
│   └── structured.jsonl             # JSON structured logs
│
├── tests/                          # 17 test modules, 48 tests
│   ├── conftest.py
│   ├── test_adaptive.py
│   ├── test_backtest.py            # 8 tests
│   ├── test_backtest_html_plotly.py # Plotly verification
│   ├── test_connectors_and_oi.py
│   ├── test_features.py
│   ├── test_llm_classifier.py
│   ├── test_metrics_endpoint.py    # /metrics + /health test
│   ├── test_news_guard.py
│   ├── test_persistence.py
│   ├── test_regime_weighting.py
│   ├── test_signal_engine_outcomes.py
│   ├── test_slippage.py
│   ├── test_structural.py
│   ├── test_structural_v2.py       # SMC tests
│   ├── test_telegram_formatter.py  # 5 tests
│   └── test_whale_tracker.py
│
└── trader_dost_arun/                # মূল প্যাকেজ
    │
    ├── core/
    │   ├── config.py               # YAML + .env loader
    │   ├── models.py               # সব ডেটা ক্লাস
    │   ├── state.py                # MarketStateStore (in-memory)
    │   ├── persistence.py          # PositionStore (SQLite)
    │   └── checkpoint.py           # State snapshot every 60s
    │
    ├── data/                       # ৫টি এক্সচেঞ্জ কানেক্টর
    │   ├── base.py                 # BasePublicConnector (defensive level parser)
    │   ├── binance.py              # Binance Futures
    │   ├── bybit.py                # Bybit
    │   ├── okx.py                  # OKX (4-element level support)
    │   ├── hyperliquid.py          # Hyperliquid (dict {px,sz} support)
    │   ├── deribit.py              # Deribit (options)
    │   ├── manager.py              # ConnectorManager
    │   └── external.py             # CoinGecko, DefiLlama, SEC, FRED
    │
    ├── features/
    │   ├── calculations.py         # ৪০+ ফিচার হিসাব
    │   ├── structural.py           # Smart Money Concepts (BOS/CHoCH/FVG/OB/Sweep)
    │   ├── orderflow.py            # Footprint, delta divergence
    │   ├── orderflow_private.py    # Kyle's lambda, spoofing detection
    │   └── liquidation_map.py      # Liquidation zone heatmap
    │
    ├── signals/
    │   ├── deterministic.py        # ১৯টি স্ট্র্যাটেজি
    │   ├── engine.py               # SignalEngine — মূল ফ্লো
    │   ├── vetoes.py               # ১১টি ভিটো চেক
    │   └── futures_vetoes.py      # ১০টি ফিউচারস ফিল্টার (F01-F10)
    │
    ├── adaptive/
    │   ├── regime.py               # HMM রেজিম (BIC + KL drift + 500 samples)
    │   ├── kelly.py                # Kelly Criterion (3% cap)
    │   ├── bayesian.py             # Beta-Binomial + hierarchical shrinkage
    │   ├── meta_label.py           # LightGBM + SHAP + Isotonic
    │   ├── exposure.py             # Portfolio gross/same-direction limit
    │   └── feature_importance.py   # Online feature importance
    │
    ├── ml/
    │   ├── historical.py           # SQLite feature store
    │   ├── online_learner.py       # Drift alarm + calibrator
    │   ├── walk_forward.py         # Purged K-fold + CPCV (1000+ samples)
    │   ├── purged_kfold.py         # Purged time-series CV
    │   └── feature_store.py        # Feature caching + stability
    │
    ├── newsguard/
    │   ├── guard.py                # NewsGuard (lifecycle + decay + impact)
    │   ├── sources.py              # RSS, Telegram, Etherscan, Nitter
    │   ├── calendar.py             # FRED economic calendar
    │   ├── embeddings.py           # Sentence-transformers similarity
    │   ├── llm_classifier.py       # GLM-4.6 batch classifier
    │   ├── whale_tracker.py        # ETH+BTC+TRON+SOL multi-chain
    │   ├── db.py                   # News replay SQLite store
    │   └── models.py               # NewsEvent, ImpactAssessment
    │
    ├── backtest/
    │   ├── engine.py               # Event-driven + slippage + funding
    │   ├── runner.py               # CLI + Plotly HTML report
    │   └── metrics.py              # Sharpe/Sortino/Calmar/PF
    │
    ├── risk/
    │   └── engine.py               # Kill switch + daily loss + RR validation
    │
    ├── execution/
    │   └── slippage.py             # 3 মোড: conservative/realistic/aggressive
    │
    └── ops/
        ├── alerts.py               # Ultra-premium Telegram formatter + counter
        ├── telegram_bot.py          # Admin bot (/mute /pause /status)
        ├── health.py               # /health + /metrics Prometheus + HealthScorer
        ├── latency.py              # p50/p95/p99 latency monitor
        └── logging_utils.py        # Structured JSON logging
```

---

## 🔄 বট কীভাবে স্ক্যান করে

```
[1] ৫০টি WebSocket সাবস্ক্রিপশন খোলে (৫ venue × ১০ symbol)
     │  • Order book depth (top 20 levels)
     │  • Live trades
     │  • Mark/Index/Funding (1s)
     │  • Liquidation events
     │  • Open Interest (REST polling, 15s)
     ▼
[2] সব ইভেন্ট একটি asyncio.Queue-তে জমা হয়
     ▼
[3] Main loop প্রতিটি ইভেন্ট প্রসেস করে:
     ├─ MarketStateStore-এ সেভ (memory, 3000 snapshots)
     ├─ Update open positions (stop/target hit?)
     ├─ Check minimum snapshots (30) পর্যন্ত অপেক্ষা
     ├─ Peer views (একই symbol অন্য venue-এ)
     ├─ External context (CoinGecko, stablecoin, macro)
     ├─ Compute 40+ features (ATR, VWAP, z-scores, CVD, OI delta...)
     ▼
[4] SignalEngine.evaluate():
     ├─ RiskEngine.allow_new_signal() — kill switch + daily loss check
     ├─ HMMRegimeDetector.observe() — রেজিম আপডেট
     ├─ build_structural_state() — BOS/CHoCH/FVG/OB/Sweep
     ├─ NewsGuard.assess() — LLM news impact
     ├─ HistoricalFeatureStore.append() — SQLite-এ সেভ
     ▼
[5] DeterministicStrategyEngine.evaluate_all()
     └─ ১৯টি স্ট্র্যাটেজি সমানে চেক → candidate signals
     ▼
[6] প্রতিটি candidate-এর জন্য:
     ├─ Regime weight check (priority_mult ≥ 0.55)
     ├─ Strategy drift alarm (recent win rate খারাপ?)
     ├─ ২১টি ভিটো ফিল্টার (সব পাস মাস্ট)
     ├─ Structural contradiction check
     ├─ RiskEngine.refine_signal() — ATR স্টপ/টার্গেট
     ├─ RR ≥ 1.25 validation
     ├─ Kelly advisory size
     ├─ LightGBM meta-label prob ≥ 0.55
     ├─ Bayesian + Meta + News confidence merge
     ├─ Isotonic calibration
     ├─ Slippage-aware fill price
     ├─ ExposureOptimizer (gross ≤ 10%, same-dir ≤ 6%)
     ├─ Cooldown (8 min same symbol+strategy)
     ├─ PositionStore-এ SQLite-এ সেভ
     └─ Accepted → priority_score sort
     ▼
[7] TelegramAlerter.signal_alert()
     └─ Ultra-premium template render করে পাঠায়
```

---

## 🎯 ১৯টি স্ট্র্যাটেজি

### Continuation (ট্রেন্ড ধরে এগোয়) — ৮টি
| # | নাম | Prior |
|---|-----|-------|
| 1 | `liquidation_cascade_continuation` | 92 |
| 2 | `order_flow_imbalance_continuation` | 89 |
| 3 | `fresh_oi_breakout_continuation` | 84 |
| 4 | `spot_index_lead_follow_through` | 78 |
| 5 | `funding_window_inventory_rebalance` | 74 |
| 6 | `inventory_skew_market_making` | 76 |
| 7 | `structural_regime_trend_follow` | 91 |
| 8 | `whale_flow_proxy_breakout` | 72 |

### Reversion (উল্টো দিকে ফিরে আসা) — ৬টি
| # | নাম | Prior |
|---|-----|-------|
| 9 | `extreme_funding_crowding_reversion` | 90 |
| 10 | `aggressor_exhaustion_absorption_fade` | 86 |
| 11 | `single_venue_premium_snapback` | 82 |
| 12 | `cross_venue_basis_dispersion_convergence` | 80 |
| 13 | `depth_wall_fade` | 83 |
| 14 | `vwap_band_mean_reversion` | 81 |

### Carry / Arb — ৪টি
| # | নাম | Prior |
|---|-----|-------|
| 15 | `spot_perp_basis_carry` | 88 |
| 16 | `funding_rate_carry_2` | 86 |
| 17 | `cross_exchange_basis_arb` | 85 |
| 18 | `vol_arb_gamma_scalp` | 79 |

### Deribit Special — ১টি
| # | নাম | Prior |
|---|-----|-------|
| 19 | `deribit_iv_shock_repricing` | 71 |

---

## 🛡️ ২১টি ভিটো ফিল্টার

প্রতিটি candidate সিগন্যাল ২১টি গেট পাস করতে হয়:

### মূল ভিটো — ১১টি
1. `spread_depth_deterioration` — স্প্রেড/ডেপথ খারাপ না
2. `wrong_leverage_regime` — continuation-এ OI বাড়ছে, reversion-এ funding extreme
3. `volatility_anomaly` — 5m vol ≤ 0.15
4. `exchange_instability` — mark-index gap ≤ 40bps, feed lag ≤ 2s
5. `macro_release_window` — FOMC/CPI/NFP টাইমে না
6. `correlation_spike` — BTC 3%+ মুভ + altcoin dispersion
7. `cross_venue_dispersion` — venue গুলোর দাম অনেক আলাদা না
8. `stablecoin_liquidity_stress` — USDT/USDC ≥ $0.997
9. `funding_timestamp_proximity` — ফান্ডিং টাইমের কাছে না
10. `liquidation_tape_against_setup` — fade-এর বিপরীতে বড় লিকুইডেশন না
11. `news_guard` — NewsGuard সাপ্রেস না বলেছে

### ফিউচারস ফিল্টার — ১০টি (F01-F10)
12. `f01_oi_market_cap_ratio` — OI/mcap ≤ 3%
13. `f02_aggregated_oi_breakout` — OI breakout OR premium ≤ 2.2
14. `f03_funding_divergence` — funding dispersion ≤ 3.0
15. `f04_cvd_price_divergence` — CVD-price divergence ≤ 2.0
16. `f05_liquidation_cluster_proximity` — লিকুইডেশন ক্লাস্টার দূরে
17. `f06_volatility_regime` — 5m vol ≤ 0.18
18. `f07_cost_basis_band` — dev_atr ≤ 5.0
19. `f08_etf_basis_regime` — stress-এ premium ≤ 1.5
20. `f09_depth_imbalance_sanity` — OFI ≤ 0.85 OR depth স্বাভাবিক
21. `f10_systemic_leverage_composite` — leverage score ≤ 1.2

---

## 🧠 অ্যাডাপ্টিভ লেয়ার

### 1. HMM রেজিম ডিটেকশন (`adaptive/regime.py`)
- **3 ইনপুট**: realized_vol_5m, trade_delta, funding_rate
- **3 রেজিম**: trending, mean_reverting, high_stress
- **500 samples** পর্যন্ত warmup (warmup-এ কোনো সিগন্যাল নয়)
- **BIC selection** across {2, 3, 4} components
- **KL divergence drift check** (> 0.5 হলে রিফিট)
- **3-tick transition confirmation** (false flip এড়াতে)
- **5 মিনিটে রিফিট**

### 2. LightGBM মেটা-লেবেল (`adaptive/meta_label.py`)
- **Per-strategy** model (dict keyed by strategy name)
- **12 ফিচার**: spread, same_side_depth, realized_vol_1m/5m, delta_oi, funding_z, premium_z, systemic_leverage, dev_atr, price/premium dispersion, cvd_price_divergence
- **Isotonic calibration**
- **Youden's J threshold tuning**
- **SHAP feature importance** (top-10)
- **Threshold**: 0.55 (নিচে রিজেক্ট)
- **SGD fallback** যদি LightGBM না থাকে

### 3. Bayesian কনফিডেন্স (`adaptive/bayesian.py`)
- **Beta-Binomial distribution**
- **Prior strength = 10** (weakly informative)
- **Hierarchical shrinkage**: 30 sample-এর কম হলে global-এর দিকে ঝুঁকছে
- **Credible interval** (95% HDI) via scipy

### 4. Kelly Criterion (`adaptive/kelly.py`)
- **Half-Kelly** (fraction = 0.5)
- **3% cap** per trade
- **Payoff ratio** correctly tracked (separate win/loss R)

### 5. Exposure Optimizer (`adaptive/exposure.py`)
- **Gross exposure ≤ 10%** of capital
- **Same-direction ≤ 6%**
- **Correlation penalty** for BTC/ETH

### 6. Online Outcome Tracker + Calibrator (`ml/online_learner.py`)
- Last 120 outcomes per (strategy, regime)
- **Drift alarm** if recent 50 vs prior 50 win rate delta > 15%
- **Calibrator**: 60% posterior + 40% live win rate

### 7. Walk-Forward (`ml/walk_forward.py`)
- **1000+ samples** দরকার
- **Purged K-fold** with 30-sample embargo
- **CPCV** (Combinatorial Purged CV) option
- **Metrics**: AUC, log-loss, Brier, precision@top20%, recall@top20%
- **Calibration curve** JSON export

---

## 💰 রিস্ক ম্যানেজমেন্ট

`trader_dost_arun/risk/engine.py`-এ `RiskEngine`:

| রিস্ক | কনফিগ | ডিফল্ট |
|------|------|--------|
| Daily loss limit | `daily_loss_limit_r` | 4R |
| Kill switch | `kill_switch_after_consecutive_losses` | 4 |
| Min RR | `min_reward_to_risk` | 1.25 |
| Min targets | `min_targets` | 1 |
| Cooldown | `per_symbol_cooldown_minutes` | 8 |
| Max daily signals | `max_daily_signals` | 200 |

### কিল সুইচ কখন অন হয়?
- টানা ৪টি লস ট্রেড হলে
- দিনে -4R হলে
- 200 সিগন্যাল শেষ হলে

পরের দিন UTC রিসেটে অফ হয়।

### Slippage Model (`execution/slippage.py`)
- **Conservative**: 5bps base + 1.0×sqrt(size/depth) (backtest validation)
- **Realistic**: 2bps base + 0.5×sqrt(size/depth) (default)
- **Aggressive**: 1bps base + 0.25×sqrt(size/depth) (optimistic)

`SignalEngine` প্রতিটি সিগন্যালে `expected_fill_price` হিসাব করে ও RR পুনরায় validate করে — স্লিপেজে পরে RR ১.০-এর নিচে গেলে সিগন্যাল রিজেক্ট (`slippage_invalidates_rr`)।

### Position Persistence (`core/persistence.py`)
- SQLite-backed (`data/positions.sqlite3`)
- বট crash হলে বা restart হলে পজিশন হারায় না
- প্রতিটি position open/close-এ disk-এ সেভ

### State Checkpoint (`core/checkpoint.py`)
- প্রতি ৬০ সেকেন্ডে state snapshot
- HMM state, Bayesian priors, calibrator state
- `data/checkpoint.json`-এ সেভ

---

## 📊 Backtest করা

বটের সাথে একটি event-driven backtest engine আছে।

### CLI দিয়ে চালানো:

```bash
python -m trader_dost_arun.backtest.runner --symbol BTCUSDT --days 90
```

### অপশন:
- `--symbol` (required): কোন সিম্বল (যেমন BTCUSDT)
- `--days`: কত দিনের ডেটা (ডিফল্ট 90)
- `--strategies`: কমা-সেপারেটেড স্ট্র্যাটেজি নাম (ডিফল্ট "all")
- `--db-path`: historical DB পাথ (ডিফল্ট `./data/historical.sqlite3`)

### আউটপুট:
- `data/backtest_reports/<timestamp>.html` — Plotly chart + metrics table
- `data/backtest_reports/<timestamp>.csv` — equity curve CSV

### Metrics যা রিপোর্টে থাকে:
- Total return
- Sharpe ratio
- Sortino ratio
- Max drawdown
- Win rate
- Payoff ratio
- Profit factor
- Expectancy
- Calmar ratio
- Per-regime breakdown

### Slippage + Funding Cost:
- **Slippage model**: conservative mode-এ বাস্তব স্লিপেজ simulate করে
- **Funding cost**: entry-exit মধ্যে funding rate cost কম করা হয়
- **Liquidation**: price 80% স্টপের দিকে গেলে liquidation

---

## 🛠️ ইনস্টল ও রান

### Step 1: Extract করুন
```bash
unzip trader_dost_arun_signal_bot_v2_fixed.zip
cd trader_dost_arun_signal_bot_v2_fixed
```

### Step 2: Virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate           # Windows
```

### Step 3: Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Environment setup
```bash
cp .env.example .env
```

`.env` ফাইল edit করুন:
```env
BRAND_NAME=Trader Dost Arun Elite
ENVIRONMENT=production
TELEGRAM_BOT_TOKEN=<আপনার_বট_টোকেন>          # BotFather থেকে
TELEGRAM_CHAT_ID=<আপনার_চ্যাট_বা_গ্রুপ_ID>     # @userinfobot থেকে
TELEGRAM_ADMIN_CHAT_ID=<আপনার_ইউজার_ID>       # admin কমান্ড এর জন্য
FRED_API_KEY=<optional>                          # economic calendar
ETHERSCAN_API_KEY=<optional>                     # whale monitor
```

### Step 5: Run
```bash
python app.py
```

বট চালু হলে লগ দেখবেন — প্রতিটি venue-এর জন্য `connected` মেসেজ আসবে। প্রথম ৩০টি snapshot জমা পর্যন্ত কোনো সিগন্যাল আসবে না।

### Step 6: Verify
```bash
# টেস্ট রান
pytest -q

# /health check
curl http://localhost:8080/health

# /metrics check
curl http://localhost:8080/metrics
```

---

## ⚙️ কনফিগারেশন

`config/defaults.yaml`-এর প্রধান সেকশন:

### Watchlist (কোন কয়েন ট্র্যাক করবে)
```yaml
watchlist:
  binance: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", ...]
  bybit: ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...]
  okx: ["BTC-USDT-SWAP", "ETH-USDT-SWAP", ...]
  hyperliquid: ["BTC-PERP", "ETH-PERP", ...]
  deribit: ["BTC-PERPETUAL", "ETH-PERPETUAL"]
```

### Risk (রিস্ক প্যারামিটার)
```yaml
risk:
  daily_loss_limit_r: 4
  kill_switch_after_consecutive_losses: 4
  min_reward_to_risk: 1.25
  min_targets: 1
  per_symbol_cooldown_minutes: 8
  max_daily_signals: 200
```

### Adaptive (অ্যাডাপ্টিভ লেয়ার)
```yaml
adaptive:
  kelly_cap: 0.03
  kelly_fraction: 0.5
  hmm_regimes: 3
  hmm_min_samples: 500
  hmm_refit_seconds: 300
  hmm_transition_confirmation_ticks: 3
  meta_label_threshold: 0.55
  max_gross_exposure: 0.10
  max_same_direction_exposure: 0.06
  prior_strength: 10
```

### ML (machine learning)
```yaml
ml:
  retention_days: 30
  walk_forward_embargo: 30
  walk_forward_alpha: 0.0001
  calibration_min_samples: 60
  prior_mean: 0.55
  drift_window: 50
  drift_alarm_threshold: 0.15
  retrain_max_rows: 1500
  min_rows_for_walk_forward: 1000
```

### Strategy Priors (১৯টি স্ট্র্যাটেজির Bayesian prior)
```yaml
strategy_priors:
  liquidation_cascade_continuation: 92
  extreme_funding_crowding_reversion: 90
  # ... 19 টি
```

### Strategy Config (ATR multiplier ও target multiple)
```yaml
strategies:
  liquidation_cascade_continuation: {atr_stop_multiplier: 0.7, target_multiple: 3.0}
  extreme_funding_crowding_reversion: {atr_stop_multiplier: 0.5, target_multiple: 1.5}
  # ... 19 টি
```

### Vetoes (ভিটো থ্রেশহোল্ড)
```yaml
vetoes:
  volatility_anomaly: {rv_5m_max: 0.15}
  exchange_instability: {max_mark_index_gap_bps: 40, max_feed_lag_seconds: 2}
  correlation_spike: {dispersion_limit: 150}
  cross_venue_dispersion: {price_dispersion_limit: 250, premium_dispersion_limit: 50}
  funding_proximity: {pre_minutes: 5, post_minutes: 3}
  liquidation_tape: {liquidation_notional_limit: 1000000}
```

### Futures Filters (F01-F10)
```yaml
futures_filters:
  f01_oi_market_cap_ratio: {max_ratio: 0.03}
  f02_aggregated_oi_breakout: {delta_oi_min: 5000, premium_z_abs_max: 2.2}
  # ... 10 টি
```

### NewsGuard
```yaml
news_guard:
  refresh_seconds: 120
  replay_db_path: ./data/news_guard_replay.sqlite3
  semantic_similarity_threshold: 0.72
  rss_sources: [...]
  x_sources: [...]
  telegram_sources: [...]
  whale_monitor: {...}
```

### Local Override
```bash
cp config/local.example.yaml config/local.yaml
```

`local.yaml`-এ যেকোনো সেটিং ওভাররাইড করতে পারেন।

---

## 📈 Observability

### HTTP Endpoints (port 8080)

#### `/health`
```json
{"status": "ok"}
```

#### `/metrics` (Prometheus format)
```
# HELP signals_total Signals emitted
# TYPE signals_total counter
signals_total 0.0

# HELP signal_veto_total Signals vetoed
# TYPE signal_veto_total counter
signal_veto_total{reason="meta_label_rejected"} 12.0

# HELP signal_latency_seconds Signal evaluation latency
# TYPE signal_latency_seconds histogram
signal_latency_seconds_bucket{le="0.005"} 0.0
...
```

### Logs
- **Plain text**: `logs/signal_bot.log`
- **Structured JSON**: `logs/structured.jsonl`

### Useful `grep` patterns:
```bash
# সব connected venues দেখুন
grep "connected" logs/signal_bot.log | head

# সব fired signals দেখুন
grep "signal fired" logs/signal_bot.log

# সব suppressed reasons দেখুন
grep "signal suppressed" logs/signal_bot.log | grep -oP "suppressed \K\w+" | sort | uniq -c

# কোনো Traceback আছে কিনা
grep -E "Traceback|AttributeError|KeyError|CRITICAL" logs/signal_bot.log
```

---

## ❓ FAQ

### Q1: বট কি নিজে ট্রেড করে?
**না**। শুধু সিগন্যাল টেলিগ্রামে পাঠায়। আপনাকে ম্যানুয়ালি ট্রেড নিতে হবে।

### Q2: কত সময় পর পর সিগন্যাল আসে?
নির্দিষ্ট নয়। মার্কেট শান্ত থাকলে ঘণ্টায় ১-২টি, ভোলাটাইল থাকলে ১০-২০টি।

### Q3: প্রতিটি সিগন্যাল কি লাভজনক?
**না**। কোনো গ্যারান্টি নেই। ML+Bayesian দিয়ে এডজি ধরার চেষ্টা করে।

### Q4: কোন সিগন্যালে বিশ্ব করব?
- `priority_score` বেশি (০.৭+)
- Confidence ৬০%+
- RR ২R+
- Confluence ৭/১০+

### Q5: Kill switch কখন অন হয়?
টানা ৪ লস বা দিনে -4R। পরদিন UTC রিসেটে অফ।

### Q6: Meta-label prob কী?
LightGBM মডেল যা বলে এই সেটআপে জেতার সম্ভাবনা। ০.৫৫-এর নিচে রিজেক্ট।

### Q7: বট কত RAM খায়?
৫০টি WebSocket + ৫০ সিম্বলের মেমোরি = ৫০০MB–১GB।

### Q8: বট crash হলে পজিশন হারাব?
**না**। SQLite-এ persist করা। Restart হলে পজিশন ফিরে আসবে।

### Q9: কোন API key দরকার?
- **টেলিগ্রাম বট টোকেন + chat ID**: মাস্ট (admin ID optional)
- **FRED API**: ম্যাক্রো ক্যালেন্ডার
- **Etherscan API**: হোয়েল মনিটর

### Q10: Binance 451 error কেন?
Binance futures API কিছু region-এ geo-blocked। Bybit/OKX/Hyperliquid/Deribit চলবে।

### Q11: Backtest কীভাবে চালাব?
```bash
python -m trader_dost_arun.backtest.runner --symbol BTCUSDT --days 90
```
HTML রিপোর্ট `data/backtest_reports/`-এ তৈরি হবে।

### Q12: Telegram কমান্ড কাজ করছে কিনা কীভাবে জানব?
বটকে `/status` message পাঠান। যদি admin chat ID ঠিক থাকে, bot সাড়া দেবে।

### Q13: ১০০০+ sample ছাড়া walk-forward চলবে?
**না**। পর্যাপ্ত ডেটা না জমলে retrain skip হবে।

### Q14: NewsGuard এর জন্য কোন API দরকার?
- FRED API key (ম্যাক্রো ক্যালেন্ডার)
- বাকি RSS/X/Telegram sources ফ্রী

### Q15: বট ২৪/৭ চালু রাখতে হবে?
হ্যাঁ। systemd বা Docker ব্যবহার করুন। systemd file তৈরি করে `/etc/systemd/system/`-এ রাখুন।

---

## ⚠️ ডিসক্লেইমার

1. **এই বট কোনো আর্থিক পরামর্শ নয়।**
2. **সিগন্যাল লাভজনক হবে — এমন কোনো গ্যারান্টি নেই।**
3. **সবসময় নিজের রিস্ক ম্যানেজমেন্ট করুন।**
4. **প্রথমে ১-২ সপ্তাহ পেপার ট্রেড করুন।**
5. **API key গোপন রাখুন।** `.env` git-এ commit করবেন না।
6. **স্টপ লস সবসময় মানুন।**
7. **লিভারেজ ২-৩x-এর বেশি না।**
8. **পজিশন সাইজ ১-২%-এর বেশি না।**
9. **ট্রেড জার্নাল রাখুন।**
10. **ট্যাক্স নিজে হিসাব করুন** (ভারতে 30% + 1% TDS)।

---

## 🎁 Bonus: Trade নেওয়ার Checklist

সিগন্যাল পেলে ট্রেড নেওয়ার আগে মানুন:

- [ ] Confidence ৬০%+ ?
- [ ] Meta prob ৬০%+ ?
- [ ] RR অন্তত ১.৫R ?
- [ ] Regime স্ট্র্যাটেজির সাথে মেলে?
- [ ] Confluence ৭/১০+ ?
- [ ] Filters 21/21 passed?
- [ ] এই সিম্বলে আগের পজিশন নেই?
- [ ] ডেইলি লস লিমিটের মধ্যে?
- [ ] স্টপ লস কোথায় জানেন?
- [ ] TP1/TP2/TP3 বুঝেছেন?
- [ ] পজিশন সাইজ ১-২% এর মধ্যে?
- [ ] Valid window এর মধ্যে এন্ট্রি নিতে পারবেন?

---

## 🚀 Quick Start (5 Steps)

```bash
# 1. Extract
unzip trader_dost_arun_signal_bot_v2_fixed.zip
cd trader_dost_arun_signal_bot_v2_fixed

# 2. Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 3. Edit .env — Telegram token + chat ID ভরুন
nano .env

# 4. Verify
pytest -q                          # সব টেস্ট পাস করবে
python app.py &                    # বট চালু
sleep 10
curl http://localhost:8080/health   # {"status": "ok"}
curl http://localhost:8080/metrics | head -5

# 5. Production
# systemd বা Docker-এ deploy করুন 24/7 চালানোর জন্য
```

---

**শুভকামনা! 🚀** এই বট একটি শক্তিশালী tool, কিন্তু সফলতা নির্ভর করে আপনার নিজের ডিসিপ্লিন ও রিস্ক ম্যানেজমেন্টের উপর। ট্রেড করার আগে পুরো গাইডটি আরেকবার পড়ুন।
