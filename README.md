# 🤖 Trader Dost Arun — Elite Signal Bot (বাংলা গাইড)

> একটি প্রোডাকশন-গ্রেড ক্রিপ্টো ফিউচারস সিগন্যাল বট যা ৫টি এক্সচেঞ্জ থেকে লাইভ অর্ডারবুক, ট্রেড, লিকুইডেশন, ফান্ডিং, OI ডেটা স্ক্যান করে, ১৯টি স্ট্র্যাটেজি দিয়ে সিগন্যাল তৈরি করে, ২১টি ভিটো ফিল্টার দিয়ে যাচাই করে, এবং টেলিগ্রামে পাঠায়। এই গাইডটি সম্পূর্ণ বাংলায়, নতুনদের জন্য লেখা।

---

## 📑 সূচিপত্র

1. [এক নজরে বট](#-এক-নজরে-বট)
2. [ফাইল স্ট্রাকচার ও প্রতিটি ফাইলের কাজ](#-ফাইল-স্ট্রাকচার-ও-প্রতিটি-ফাইলের-কাজ)
3. [বট কীভাবে স্ক্যান করে (পূর্ণ ফ্লো)](#-বট-কীভাবে-স্ক্যান-করে-পূর্ণ-ফ্লো)
4. [১৯টি স্ট্র্যাটেজি ফিল্টার (বিস্তারিত)](#-১৯টি-স্ট্র্যাটেজি-ফিল্টার-বিস্তারিত)
5. [ভিটো ফিল্টার — ২১টি গেট (কবজা)](#-ভিটো-ফিল্টার--২১টি-গেট-কবজা)
6. [অ্যাডাপ্টিভ লেয়ার (HMM রেজিম + Kelly + Bayesian + Meta-Label + Exposure)](#-অ্যাডাপ্টিভ-লেয়ার)
7. [রিস্ক ম্যানেজমেন্ট কীভাবে কাজ করে](#-রিস্ক-ম্যানেজমেন্ট-কীভাবে-কাজ-করে)
8. [সিগন্যাল কেমন দেখতে হবে (টেলিগ্রাম মেসেজ বোঝা)](#-সিগন্যাল-কেমন-দেখতে-হবে-টেলিগ্রাম-মেসেজ-বোঝা)
9. [সিগন্যাল কখন ফায়ার হয় (স্টেপ-বাই-স্টেপ)](#-সিগন্যাল-কখন-ফায়ার-হয়-স্টেপ-বাই-স্টেপ)
10. [ইনস্টল ও রান করার নিয়ম](#-ইনস্টল-ও-রান-করার-নিয়ম)
11. [কনফিগারেশন (defaults.yaml) ব্যাখ্যা](#-কনফিগারেশন-defaultsyaml-ব্যাখ্যা)
12. [টেস্ট চালানো](#-টেস্ট-চালানো)
13. [ডিপ্লয়মেন্ট (Docker / systemd)](#-ডিপ্লয়মেন্ট-docker--systemd)
14. [প্রায়শই জিজ্ঞাসিত প্রশ্ন (FAQ)](#-প্রায়শই-জিজ্ঞাসিত-প্রশ্ন-faq)
15. [সতর্কতা ও ডিসক্লেইমার](#-সতর্কতা-ও-ডিসক্লেইমার)

---

## 🚀 এক নজরে বট

**Trader Dost Arun Elite Signal Bot** হলো একটি অটোমেটেড ক্রিপ্টো ফিউচারস স্ক্যানার যা:

- **৫টি এক্সচেঞ্জ** থেকে লাইভ ডেটা নেয়: Binance, Bybit, OKX, Hyperliquid, Deribit
- **১০টি কয়েন** ট্র্যাক করে: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, ARB
- **১৯টি স্ট্র্যাটেজি** সমানে চালায় প্রতিটি স্ক্যানে
- **২১টি ভিটো ফিল্টার** দিয়ে প্রতিটি সিগন্যাল যাচাই করে (নিরাপত্তা গেট)
- **HMM রেজিম ডিটেকশন** দিয়ে বুঝে trending / mean-reverting / high_stress অবস্থা
- **Bayesian + Meta-Label ML** দিয়ে কনফিডেন্স স্কোর তৈরি করে
- **Kelly Criterion** দিয়ে পজিশন সাইজ সাজেস্ট করে
- **NewsGuard** দিয়ে খবর/ম্যাক্রো/হোয়েল মুভমেন্ট মনিটর করে
- সবশেষে **টেলিগ্রামে** সুন্দর ফরম্যাটে সিগন্যাল পাঠায়

> ⚠️ এটি শুধুমাত্র **সিগন্যাল বট** — নিজে কোনো ট্রেড করে না। সিগন্যাল পেলে আপনি নিজে ম্যানুয়ালি ট্রেড নেবেন।

---

## 📁 ফাইল স্ট্রাকচার ও প্রতিটি ফাইলের কাজ

নিচে সম্পূর্ণ ফোল্ডার স্ট্রাকচার দেওয়া হলো। প্রতিটি ফাইলের পাশে বাংলায় কাজ বোঝানো হয়েছে:

```
trader_dost_arun_elite_signal_bot/
│
├── app.py                          # 🎯 মূল এন্ট্রি পয়েন্ট — এখান থেকে বট চলে
├── README.md                       # এই ফাইল
├── requirements.txt                # যেসব Python লাইব্রেরি দরকার (httpx, websockets, sklearn ইত্যাদি)
├── Dockerfile                      # Docker ইমেজ বানানোর রেসিপি
├── docker-compose.yml              # Docker-এ বট চালানোর কনফিগ
├── pytest.ini                      # pytest টেস্ট কনফিগ
├── .env.example                    # এনভায়রনমেন্ট ভ্যারিয়েবলের টেমপ্লেট
│
├── config/
│   ├── defaults.yaml               # সব ডিফল্ট সেটিং (watchlist, risk, strategies, vetoes)
│   └── local.example.yaml          # লোকাল ওভাররাইডের নমুনা
│
├── data/
│   ├── historical.sqlite3          # SQLite ডেটাবেস — পুরোনো ফিচার + আউটকাম সেভ থাকে
│   └── models/                     # ML মডেল (meta_label_live.joblib) এখানে সেভ হয়
│
├── scripts/
│   └── run_bot.sh                  # বট চালু করার ব্যাশ স্ক্রিপ্ট
│
├── systemd/
│   └── trader-dost-elite.service   # systemd সার্ভিস ফাইল (লিনাক্সে ব্যাকগ্রাউন্ডে চালানোর জন্য)
│
├── tests/                          # pytest টেস্ট ফাইল (৯টি টেস্ট মডিউল)
│   ├── conftest.py
│   ├── test_adaptive.py
│   ├── test_connectors_and_oi.py
│   ├── test_elite_upgrade.py
│   ├── test_features.py
│   ├── test_news_guard.py
│   ├── test_regime_weighting.py
│   ├── test_signal_engine_outcomes.py
│   ├── test_structural.py
│   └── test_vetoes.py
│
└── trader_dost_arun/               # মূল প্যাকেজ (সব কোড এখানে)
    │
    ├── __init__.py
    │
    ├── core/                       # কোর ডেটা স্ট্রাকচার ও কনফিগ
    │   ├── config.py               # YAML + .env লোড করে Settings বানায়
    │   ├── models.py               # সব ডেটা ক্লাস: Signal, Trade, MarketSnapshot, StructuralState ইত্যাদি
    │   └── state.py                # MarketStateStore — সব লাইভ ডেটা মেমোরিতে রাখে
    │
    ├── data/                       # এক্সচেঞ্জ কানেক্টর (WebSocket + REST)
    │   ├── base.py                 # BasePublicConnector — সব কানেক্টরের বেস ক্লাস
    │   ├── binance.py              # Binance Futures কানেক্টর
    │   ├── bybit.py                # Bybit কানেক্টর
    │   ├── okx.py                  # OKX কানেক্টর
    │   ├── hyperliquid.py          # Hyperliquid কানেক্টর
    │   ├── deribit.py              # Deribit (অপশন) কানেক্টর
    │   ├── manager.py              # ConnectorManager — সব কানেক্টর একসাথে চালায়
    │   └── external.py             # CoinGecko, DefiLlama, SEC, Etherscan, FRED থেকে বাইরের ডেটা
    │
    ├── features/                   # ফিচার ইঞ্জিনিয়ারিং
    │   ├── calculations.py         # ৪০+ ফিচার তৈরি করে: ATR, VWAP, OI delta, z-scores, CVD ইত্যাদি
    │   └── structural.py           # Price Action স্ট্রাকচার: BOS, CHoCH, FVG, Order Block, Liquidity Sweep
    │
    ├── signals/                    # সিগন্যাল ইঞ্জিন (বটের মস্তিষ্ক)
    │   ├── deterministic.py        # ১৯টি স্ট্র্যাটেজি এখানে লেখা
    │   ├── engine.py               # SignalEngine — সব একসাথে জোড়া লাগায়
    │   ├── vetoes.py               # ১১টি ভিটো চেক + futures_vetoes কল করে
    │   └── futures_vetoes.py       # আরও ১০টি ফিউচারস-স্পেসিফিক ফিল্টার (F01–F10)
    │
    ├── adaptive/                   # অ্যাডাপ্টিভ / ML লেয়ার
    │   ├── regime.py               # HMM দিয়ে ৩টি রেজিম শনাক্ত করে (trending/mean_reverting/high_stress)
    │   ├── kelly.py                # Kelly Criterion দিয়ে পজিশন সাইজ
    │   ├── bayesian.py             # Beta-Binomial Bayesian কনফিডেন্স
    │   ├── meta_label.py           # SGDClassifier ML মডেল (meta-labeling)
    │   ├── exposure.py             # Portfolio exposure লিমিট ম্যানেজ করে
    │   └── feature_importance.py   # কোন ফিচার বেশি কাজে লাগছে ট্র্যাক করে
    │
    ├── ml/                         # অফলাইন ML পাইপলাইন
    │   ├── historical.py           # SQLite-এ ফিচার সেভ ও রিট্রিভ করে
    │   ├── online_learner.py       # Drift ট্র্যাকিং + কনফিডেন্স ক্যালিব্রেটর
    │   └── walk_forward.py         # Walk-forward ক্রস-ভ্যালিডেশন (anti-overfit)
    │
    ├── newsguard/                  # নিউজ ও ইভেন্ট গার্ড
    │   ├── guard.py                # NewsGuard — সব নিউজ সোর্স মার্জ করে ইমপ্যাক্ট হিসাব করে
    │   ├── sources.py              # RSS, Telegram, Etherscan থেকে নিউজ টানে
    │   ├── calendar.py             # FRED ইকনোমিক ক্যালেন্ডার
    │   ├── embeddings.py           # টেক্সট সেম্যান্টিক সিমিলারিটি (ডুপ্লিকেট নিউজ ধরতে)
    │   ├── db.py                   # নিউজ রিপ্লে SQLite স্টোর
    │   └── models.py               # NewsEvent, ImpactAssessment ডেটা ক্লাস
    │
    ├── risk/                       # রিস্ক ম্যানেজমেন্ট
    │   └── engine.py               # RiskEngine — daily loss, kill switch, RR চেক, ATR স্টপ
    │
    └── ops/                        # অপারেশনাল টুলস
        ├── alerts.py               # TelegramAlerter — টেলিগ্রামে সিগন্যাল পাঠায়
        ├── health.py               # HealthScorer — এক্সচেঞ্জ স্বাস্থ্য স্কোর
        ├── latency.py              # LatencyMonitor — p50/p95/p99 লেটেন্সি ট্র্যাক
        └── logging_utils.py        # লগ কনফিগার করে
```

### 🔑 গুরুত্বপূর্ণ ফাইল কোনগুলো?

যদি শুধু ৫টি ফাইল দেখেন, তাহলে এই ৫টি দেখবেন:

| ফাইল | কেন দেখবেন |
|------|-----------|
| `app.py` | বট কীভাবে চলে সেটা বুঝবেন |
| `config/defaults.yaml` | কোন কয়েন, কোন স্ট্র্যাটেজি, কী রিস্ক প্যারামিটার — সব এখানে |
| `trader_dost_arun/signals/deterministic.py` | ১৯টি স্ট্র্যাটেজির লজিক এখানে |
| `trader_dost_arun/signals/engine.py` | সিগন্যাল কীভাবে ফায়ার হয় — মূল ফ্লো এখানে |
| `trader_dost_arun/ops/alerts.py` | টেলিগ্রাম মেসেজ কেমন দেখায় এখানে |

---

## 🔄 বট কীভাবে স্ক্যান করে (পূর্ণ ফ্লো)

বট যখন চালু হয়, নিচের ফ্লোটি চলতে থাকে। এটি একটি **ইনফিনিট লুপ** — থামে না যতক্ষণ না বট বন্ধ করা হয়।

### স্টেপ ১: কানেক্টর চালু হয় (`app.py` → `ConnectorManager.start()`)

`ConnectorManager` ৫টি এক্সচেঞ্জের জন্য ১০টি করে (মোট ৫০টি) WebSocket কানেকশন খোলে। প্রতিটি কানেকশন একটি আলাদা `asyncio.Task`-এ চলে। প্রতিটি কানেক্টর সাবস্ক্রাইব করে:

- **Order book depth** (টপ ২০ লেভেল, ১০০ms আপডেট)
- **Live trades** (প্রতিটি buy/sell)
- **Mark price + Index price + Funding rate** (১ সেকেন্ডে একবার)
- **Liquidation events** (forceOrder stream)
- **Open Interest** (REST পোলিং, ১৫ সেকেন্ডে একবার)

Binance-এর উদাহরণ: `BTCUSDT@depth20@100ms`, `BTCUSDT@trade`, `BTCUSDT@markPrice@1s`, `BTCUSDT@forceOrder` — এই ৪টি স্ট্রিম একসাথে।

### স্টেপ ২: ডেটা একটি কিউতে জমা হয়

সব কানেক্টর তাদের পার্স করা ইভেন্ট (MarketSnapshot / Trade / LiquidationEvent) একটি শেয়ার্ড `asyncio.Queue`-তে পাঠায়।

### স্টেপ ৩: মেইন লুপ প্রতিটি ইভেন্ট প্রসেস করে

`app.py`-এর `while True:` লুপ প্রতিটি ইভেন্ট তুলে নেয় এবং:

1. **`MarketStateStore`**-এ সেভ করে (মেমোরিতে, সর্বোচ্চ ৩০০০ স্ন্যাপশট)
2. **সিম্বলের পুরোনো পজিশন চেক** করে — stop/target হিট হলে ক্লোজ করে (হাইপোথেটিক্যালি)
3. **দেখে যথেষ্ট ডেটা জমেছে কিনা** — `min_snapshots_before_signals: 30` অর্থাৎ কমপক্ষে ৩০টি স্ন্যাপশট লাগবে সিগন্যাল দেওয়ার জন্য। এর আগে কোনো সিগন্যাল আসবে না।
4. **পিয়ার ভিউস** বের করে — একই সিম্বল অন্য এক্সচেঞ্জে কেমন আছে (যেমন BTCUSDT বিনান্সে, BTC-USDT-SWAP OKX-এ)
5. **বাইরের কন্টেক্সট** নেয় — CoinGecko দাম, stablecoin স্ট্রেস, ম্যাক্রো ইভেন্ট, হোয়েল ফ্লো
6. **ফিচার কম্পিউট করে** — `compute_features()` ফাংশন ৪০+ ফিচার বানায় (ATR, VWAP, z-scores, OI delta, funding z, premium z, CVD, systemic leverage ইত্যাদি)
7. **সিগন্যাল ইঞ্জিন কল করে** — `signal_engine.evaluate()`

### স্টেপ ৪: সিগন্যাল ইঞ্জিন ভেতরে কী করে?

`SignalEngine.evaluate()` ফাংশন আসলে বটের মস্তিষ্ক। সিরিয়ালি নিচের কাজগুলো করে:

```
[1] RiskEngine.allow_new_signal() — কিল সুইচ / ডেইলি লস চেক
        ↓ (ব্লক হলে থেমে যায়)
[2] HMMRegimeDetector.observe() — রেজিম আপডেট (trending/mean_reverting/high_stress/warmup)
        ↓
[3] build_structural_state() — BOS, CHoCH, FVG, Order Block, Liquidity Sweep খুঁজে বের করে
        ↓
[4] NewsGuard.assess() — নিউজ ইমপ্যাক্ট, সাপ্রেস, কুলডাউন চেক
        ↓
[5] HistoricalFeatureStore.append() — SQLite-এ ফিচার সেভ
        ↓
[6] DeterministicStrategyEngine.evaluate_all() — ১৯টি স্ট্র্যাটেজি সমানে চেক
        ↓ (যেগুলো পাস করে সেগুলো candidate সিগন্যাল)
[7] প্রতিটি candidate-এর জন্য:
     ├─ Regime weighting (1.22x / 0.74x / 1.35x ইত্যাদি)
     ├─ Strategy drift alarm চেক (পুরোনো উইনরেট খারাপ গেলে ব্লক)
     ├─ VetoEngine.evaluate() — ২১টি ভিটো গেট
     ├─ Structural contradiction চেক
     ├─ RiskEngine.refine_signal() — ATR স্টপ ও টার্গেট সাজায়
     ├─ RiskEngine.validate_candidate() — min RR 1.25, min targets 1
     ├─ Kelly size — advisory_size_fraction হিসাব
     ├─ Bayesian confidence + Meta-label probability মার্জ
     ├─ Meta-label threshold (0.55) — নিচে হলে রিজেক্ট
     ├─ Confidence calibrator
     ├─ ExposureOptimizer — gross/same-direction লিমিট চেক
     ├─ Cooldown চেক (৮ মিনিট একই সিম্বল+স্ট্র্যাটেজিতে নতুন সিগন্যাল নয়)
     └─ সব পাস হলে → accepted লিস্টে যায়
        ↓
[8] accepted সিগন্যালগুলো priority_score অনুযায়ী সর্ট হয়
        ↓
[9] app.py প্রতিটি accepted সিগন্যাল TelegramAlerter.signal_alert()-এ পাঠায়
```

### স্টেপ ৫: টেলিগ্রামে মেসেজ যায়

যে সিগন্যালগুলো `Direction.FLAT` নয় এবং `suppressed_reason` নেই, সেগুলো টেলিগ্রামে পাঠানো হয়।

---

## 🎯 ১৯টি স্ট্র্যাটেজি ফিল্টার (বিস্তারিত)

`trader_dost_arun/signals/deterministic.py`-এ ১৯টি স্ট্র্যাটেজি লেখা। প্রতিটির কাজ নিচে:

### A. Continuation স্ট্র্যাটেজি (ট্রেন্ড ধরে এগোয়) — ৭টি

#### 1. `liquidation_cascade_continuation` (prior: 92)
- **কী খোঁজে**: বড় লিকুইডেশন ক্যাসকেড (liq_zscore > 2.3), OI বাড়ছে, adverse depth রিপ্লেনিশ হচ্ছে না
- **কেন**: যখন বড় লিকুইডেশন হয়, প্রাইস সাধারণত সেই দিকেই চলতে থাকে (cascade)
- **Stop**: 0.7 × ATR
- **Targets**: 1.5R ও 3R
- **Confirmations**: liquidation burst, range break, delta OI aligned, adverse depth not replenishing

#### 2. `order_flow_imbalance_continuation` (prior: 89)
- **কী খোঁজে**: OFI z-score > 2 (অর্ডার বুকে একদিকে ভারী), same-side depth 1.4x বেশি
- **কেন**: বায়/সেল সাইডে বড় অর্ডার থাকলে প্রাইস সেদিকেই যায়
- **Stop**: 1.0 × ATR
- **Target**: 2.0R

#### 3. `fresh_oi_breakout_continuation` (prior: 84)
- **কী খোঁজে**: delta_oi > 10,000 (নতুন পজিশন খোলা হচ্ছে), premium z-score < 2.0, সাম্প্রতিক ২০-ক্যান্ডল রেঞ্জ ব্রেকআউট
- **কেন**: নতুন টাকা ঢুকছে + রেঞ্জ ভাঙলে ট্রেন্ড শুরু
- **Stop**: 1.0 × ATR (breakout লেভেলের উপরে/নিচে)
- **Target**: 1.8R (high-low range × 1.5)

#### 4. `spot_index_lead_follow_through` (prior: 78)
- **কী খোঁজে**: spot/index price ও mark price-এর গ্যাপ ≥ 4, premium z-score < 1.5
- **কেন**: spot এগিয়ে গেলে perp ফলো করে
- **Stop**: 1.0 × ATR
- **Target**: 0.8 × gap

#### 5. `funding_window_inventory_rebalance` (prior: 74)
- **কী খোঁজে**: funding_rate ≥ 0.0001, OI এলিভেটেড, post-funding imbalance
- **কেন**: ফান্ডিং টাইমে ইনভেন্টরি শিফট হয়, সেই মুভমেন্ট ধরা
- **Stop**: 1.0 × ATR
- **Target**: rolling VWAP

#### 6. `inventory_skew_market_making` (prior: 76)
- **কী খোঁজে**: same-side depth ≥ 1.5× adverse depth, microprice lead
- **কেন**: মার্কেট মেকার ইনভেন্টরি স্কিউ থেকে ছোট মুভমেন্ট
- **Stop**: 0.6 × ATR
- **Target**: 0.8 × ATR

#### 7. `structural_regime_trend_follow` (prior: 91)
- **কী খোঁজে**: MTF alignment, BOS (Break of Structure), OI confirmation
- **কেন**: classic trend-follow — মাল্টি-টাইমফ্রেম এলাইনমেন্ট থাকলে বড় ট্রেন্ড
- **Stop**: 1.5 × ATR
- **Targets**: 3R ও 5R (দুটি)

#### 8. `whale_flow_proxy_breakout` (prior: 72)
- **কী খোঁজে**: |net_whale_usd| ≥ $5M (Etherscan থেকে)
- **কেন**: হোয়েল টাকা ঢুকালে ব্রেকআউট
- **Stop**: 1.0 × ATR
- **Target**: 2.0R

### B. Reversion স্ট্র্যাটেজি (উল্টো দিকে ফিরে আসা) — ৬টি

#### 9. `extreme_funding_crowding_reversion` (prior: 90)
- **কী খোঁজে**: |funding_z| ≥ 2.5, delta_oi ≠ 0, |premium_z| ≥ 1.2
- **কেন**: এক্সট্রিম ফান্ডিং = একদিকে জমা ভিড় = রিভার্সাল কাছে
- **Stop**: 0.5 × ATR
- **Targets**: session VWAP, rolling VWAP

#### 10. `aggressor_exhaustion_absorption_fade` (prior: 86)
- **কী খোঁজে**: CVD এক্সট্রিম (≥1000), কিন্তু প্রাইস বড় মুভ নেই (muted progress), delta_oi ≥ 0
- **কেন**: বায়ার/সেলার ক্লান্ত হলে রিভার্সাল
- **Stop**: 1.0 × ATR
- **Targets**: session VWAP, POC

#### 11. `single_venue_premium_snapback` (prior: 82)
- **কী খোঁজে**: |premium_z| ≥ 2, |delta_oi| ≤ 10,000
- **কেন**: এক ভেন্যুতে প্রিমিয়াম বেশি = সেখানে ফিরে আসবে index-এর কাছে
- **Stop**: 0.75 × ATR
- **Targets**: midpoint, index price

#### 12. `cross_venue_basis_dispersion_convergence` (prior: 80)
- **কী খোঁজে**: অন্য ভেন্যুর প্রিমিয়াম থেকে নিজের প্রিমিয়াম ৫+ দূরে
- **কেন**: cross-venue basis কনভার্জ করবে
- **Stop**: 1.0 × ATR
- **Target**: index ± peer mean premium

#### 13. `depth_wall_fade` (prior: 83)
- **কী খোঁজে**: bid/ask wall_ratio ≥ 3.0, VWAP থেকে 0.4 ATR দূরে
- **কেন**: বড় ডেপথ ওয়াল প্রাইস টেনে আনে
- **Stop**: 0.8 × ATR
- **Targets**: rolling VWAP, session VWAP

#### 14. `vwap_band_mean_reversion` (prior: 81)
- **কী খোঁজে**: dev_atr ≥ 2.5 (rolling VWAP থেকে অনেক দূরে)
- **কেন**: VWAP থেকে অনেক দূরে গেলে ফিরে আসে
- **Stop**: 0.9 × ATR
- **Targets**: rolling VWAP, session VWAP

### C. Carry / Arb স্ট্র্যাটেজি — ৪টি

#### 15. `spot_perp_basis_carry` (prior: 88)
- **কী খোঁজে**: |basis_bps| ≥ 8, |premium_z| ≥ 1.0
- **কেন**: spot-perp basis ডিসলোকেশন থেকে carry edge
- **Stop**: 0.6 × ATR
- **Target**: index price

#### 16. `funding_rate_carry_2` (prior: 86)
- **কী খোঁজে**: |funding_z| ≥ 2.0
- **কেন**: এক্সট্রিম ফান্ডিং থেকে carry compression
- **Stop**: 0.8 × ATR
- **Targets**: rolling VWAP, session VWAP

#### 17. `cross_exchange_basis_arb` (prior: 85)
- **কী খোঁজে**: peer premium mean থেকে নিজের premium ৫+ দূরে
- **কেন**: cross-exchange basis মিন রিভার্সাল
- **Stop**: 0.8 × ATR
- **Target**: entry - gap

#### 18. `vol_arb_gamma_scalp` (prior: 79)
- **কী খোঁজে**: শুধু Deribit-এ। |IV - realized vol| ≥ 0.05
- **কেন**: IV ও realized vol-এর গ্যাপ থেকে vol arb
- **Stop**: 0.9 × ATR
- **Target**: 1.2 × ATR

### D. Deribit স্পেশাল স্ট্র্যাটেজি — ১টি

#### 19. `deribit_iv_shock_repricing` (prior: 71)
- **কী খোঁজে**: শুধু Deribit-এ। ATM IV ≥ 1.8 OR put-call skew ≥ 0.05
- **কেন**: options IV শক হলে perp রিপ্রাইসিং করে
- **Stop**: 1.0 × ATR
- **Target**: 1.2 × ATR

> **মোট স্ট্র্যাটেজি**: ৭ (continuation) + ৬ (reversion) + ৪ (carry/arb) + ১ (deribit special) + ১ (whale) = **১৯টি**

### 📊 Strategy Priors (বেস কনফিডেন্স)

`config/defaults.yaml`-এ প্রতিটি স্ট্র্যাটেজির একটি prior score দেওয়া (0-100)। এটি হলো Bayesian আগের বিশ্বাস যে এই স্ট্র্যাটেজি জিতবে। যেমন:

- `liquidation_cascade_continuation`: 92 (সবচেয়ে বেশি বিশ্বস্ত)
- `whale_flow_proxy_breakout`: 72 (কম বিশ্বস্ত)

লাইভ ট্রেড হওয়ার সাথে সাথে Beta-Binomial আপডেট হয়, কনফিডেন্স ক্রমে রিয়েলিটির কাছে যায়।

---

## 🛡️ ভিটো ফিল্টার — ২১টি গেট (কবজা)

প্রতিটি candidate সিগন্যাল ২১টি ভিটো চেক পাস করতে হয়। যেকোনো একটি ফেল হলে সিগন্যাল সাপ্রেস হয়ে যায়।

### A. মূল ভিটো (`signals/vetoes.py`-এ) — ১১টি

| # | নাম | কী চেক করে |
|---|-----|-----------|
| 1 | `spread_depth_deterioration` | স্প্রেড ৯০তম পার্সেন্টাইলের উপরে না, depth ২৫তম পার্সেন্টাইলের নিচে না, slippage ৩৫% target-এর নিচে |
| 2 | `wrong_leverage_regime` | continuation স্ট্র্যাটেজির জন্য delta_oi > 0, reversion-এর জন্য funding_z ≥ 1 বা premium_z ≥ 1 |
| 3 | `volatility_anomaly` | realized_vol_5m ≤ 0.15 (অস্বাভাবিক হলে সিগন্যাল নয়, লিকুইডেশন ক্যাসকেড ছাড়া) |
| 4 | `exchange_instability` | mark-index গ্যাপ ≤ 40 bps, ফিড ল্যাগ ≤ ২ সেকেন্ড |
| 5 | `macro_release_window` | ম্যাক্রো রিলিজের ২০ মিনিটের মধ্যে না |
| 6 | `correlation_spike` | BTC ৩%+ মুভ করলে ও price dispersion > 150 হলে altcoin সিগন্যাল নয় |
| 7 | `cross_venue_dispersion` | price dispersion ≤ 250, premium dispersion ≤ 50 |
| 8 | `stablecoin_liquidity_stress` | USDT/USDC < $0.997 হলে সিগন্যাল নয় (লিকুইডেশন ক্যাসকেড ছাড়া) |
| 9 | `funding_timestamp_proximity` | ফান্ডিং টাইমের -৩ থেকে +৫ মিনিটের মধ্যে সিগন্যাল নয় |
| 10 | `liquidation_tape_against_setup` | fade স্ট্র্যাটেজির বিপরীতে বড় লিকুইডেশন ($1M+) হলে ব্লক |
| 11 | `news_guard` | NewsGuard suppress বা delay বললে ব্লক |

### B. ফিউচারস ফিল্টার প্যাক (`signals/futures_vetoes.py`-এ) — ১০টি

| # | নাম | কী চেক করে |
|---|-----|-----------|
| 12 | `f01_oi_market_cap_ratio` | OI/Market cap ≤ 0.03 (৩% এর বেশি OI হলে খুব রিস্কি) |
| 13 | `f02_aggregated_oi_breakout` | delta_oi ≥ 5,000 OR |premium_z| ≤ 2.2 |
| 14 | `f03_funding_divergence` | funding dispersion ≤ 3.0 (cross-venue ফান্ডিং বেশি আলাদা হলে ব্লক) |
| 15 | `f04_cvd_price_divergence` | cvd_price_divergence ≤ 2.0 (CVD ও প্রাইস অনেক আলাদা হলে ব্লক) |
| 16 | `f05_liquidation_cluster_proximity` | fade/reversion/snapback-এর জন্য লিকুইডেশন ক্লাস্টার কাছে (2 ATR) ও $1.5M-এর কম |
| 17 | `f06_volatility_regime` | realized_vol_5m ≤ 0.18 |
| 18 | `f07_cost_basis_band` | dev_atr ≤ 5.0 (VWAP থেকে অনেক দূরে গেলে ব্লক) |
| 19 | `f08_etf_basis_regime` | stablecoin stress-এ premium_z ≤ 1.5 |
| 20 | `f09_depth_imbalance_sanity` | OFI ≤ 0.85 OR same-side depth ≤ 1.2× adverse |
| 21 | `f10_systemic_leverage_composite` | systemic leverage score ≤ 1.2 (funding+liq+OI composite) |

> **মনে রাখবেন**: ১৯টি স্ট্র্যাটেজি থেকে আসা প্রতিটি candidate এই ২১টি গেট পাস করতে হবে। এটাই বটের নিরাপত্তা স্তর।

---

## 🧠 অ্যাডাপ্টিভ লেয়ার

বট শুধু স্ট্যাটিক রুল চালায় না — নিচের ৫টি অ্যাডাপ্টিভ কম্পোনেন্ট ক্রমাগত শেখে ও সাজে করে:

### 1. HMM রেজিম ডিটেক্টর (`adaptive/regime.py`)

`GaussianHMM` (hmmlearn) দিয়ে প্রতিটি সিম্বলের জন্য আলাদা মডেল। ৩টি ইনপুট:

- `realized_vol_5m` (5-মিনিট রিয়েলাইজড ভোলাটিলিটি)
- `trade_delta` (CVD-র সাম্প্রতিক মান)
- `funding_rate`

৩টি রেজিম শনাক্ত হয়:

- **`trending`** — ট্রেন্ড চলছে, continuation স্ট্র্যাটেজিগুলো ১.২২x আপ-ওয়েটেড
- **`mean_reverting`** — রেঞ্জ, reversion স্ট্র্যাটেজিগুলো ১.১৮x আপ-ওয়েটেড
- **`high_stress`** — ভোলাটাইল/ক্রাইসিস, শুধু `liquidation_cascade_continuation` ১.৩৫x, বাকিগুলো ০.৫৬–০.৬৮x
- **`warmup`** — শুরুর ৫০ স্যাম্পল পর্যন্ত, কোনো রিয়েল রেজিম নেই

রিফিট হয় প্রতি ৫ মিনিটে। ট্রানজিশন কনফার্মেশন লাগে ৩ টিক (যাতে false flip না হয়)।

### 2. Kelly Criterion সাইজার (`adaptive/kelly.py`)

Kelly formula দিয়ে advisory position size হিসাব করে:

```
raw = win_rate - (1 - win_rate) / payoff
bounded = max(0, raw × 0.5)   # half-Kelly
final = min(bounded, 0.03)    # max 3% of capital
```

- `kelly_fraction = 0.5` (half-Kelly, কনজারভেটিভ)
- `kelly_cap = 0.03` (একটি ট্রেডে সর্বোচ্চ ৩% ক্যাপিটাল)

### 3. Bayesian কনফিডেন্স মডেল (`adaptive/bayesian.py`)

Beta-Binomial ডিস্ট্রিবিউশন দিয়ে প্রতিটি (strategy, regime) কম্বোর জন্য কনফিডেন্স রাখে।

- **Prior**: `strategy_priors` থেকে (যেমন 92% হলে α=9.2, β=0.8)
- **Update**: প্রতিটি ট্রেড ক্লোজ হলে win হলে α+1, লস হলে β+1
- **আউটপুট**: mean confidence ও lower 95% confidence bound

### 4. Meta-Label ML মডেল (`adaptive/meta_label.py`)

SGDClassifier (logistic regression) দিয়ে একটি meta-label মডেল। ১২টি ফিচার ইনপুট:

```
spread, same_side_depth, realized_vol_1m, realized_vol_5m,
delta_oi, funding_zscore, premium_zscore, systemic_leverage_score,
dev_atr, price_dispersion, premium_dispersion, cvd_price_divergence
```

- আউটপুট: এই সেটআপে win হওয়ার সম্ভাবনা (0–1)
- Threshold: 0.55 (এর নিচে সিগন্যাল রিজেক্ট)
- Online learning: প্রতিটি ট্রেড ক্লোজ হলে `partial_fit`
- Walk-forward retraining: পর্যাপ্ত ডেটা (১০০+ স্যাম্পল) জমলে অফলাইন রিট্রেইন

### 5. Exposure Optimizer (`adaptive/exposure.py`)

পোর্টফোলিও-লেভেল লিমিট:

- `max_gross_exposure = 0.10` (মোট এক্সপোজার ক্যাপিটালের ১০%)
- `max_same_direction = 0.06` (একদিকে সর্বোচ্চ ৬%)
- Correlation penalty: BTC/ETH কোরিলেশন হলে size ২৫–১০০% স্কেল করে

### 6. Online Outcome Tracker + Calibrator (`ml/online_learner.py`)

- প্রতিটি (strategy, regime) কম্বোর শেষ ১২০টি আউটকাম রাখে
- **Drift alarm**: সাম্প্রতিক ৫০টি ও তার আগের ৫০টির উইনরেট পার্থক্য > ১৫% হলে strategy drift — ব্লক
- **Calibrator**: posterior-কে live win-rate দিয়ে blend করে (60% posterior + 40% live)

### 7. Walk-Forward Meta-Labeler (`ml/walk_forward.py`)

পর্যাপ্ত ডেটা জমলে (১০০+ লেবেলযুক্ত রো) ৫-ফোল্ড walk-forward ভ্যালিডেশন করে:

- ৩০-স্যাম্পল embargo (data leakage এড়াতে)
- AUC, log-loss, Brier score রিপোর্ট
- বেস্ট মডেল `data/models/meta_label_live.joblib`-এ সেভ
- বট রিস্টার্ট হলে এই মডেল লোড হয়

---

## 💰 রিস্ক ম্যানেজমেন্ট কীভাবে কাজ করে

`trader_dost_arun/risk/engine.py`-এ `RiskEngine` ক্লাস আছে। এটি ৪টি কাজ করে:

### ১. ডেইলি রিসেট (`maybe_reset`)
প্রতিদিন UTC তারিখ বদলালে রিসেট হয়:
- `daily_realized_r = 0`
- `consecutive_losses = 0`
- `kill_switch_active = False`
- `daily_signal_count = 0`

### ২. নতুন সিগন্যাল এলাউন্স চেক (`allow_new_signal`)
নিচের যেকোনো একটি সত্য হলে নতুন সিগন্যাল ব্লক:

| শর্ত | কনফিগ | ব্লক রিজন |
|------|-------|----------|
| Kill switch active | — | `kill_switch_active` |
| Daily realized R ≤ -4R | `daily_loss_limit_r: 4` | `daily_hypothetical_loss_limit` |
| Daily signals ≥ 200 | `max_daily_signals: 200` | `daily_signal_cap` |

### ৩. সিগন্যাল রিফাইন (`refine_signal`)
প্রতিটি সিগন্যালের স্টপ ও টার্গেট স্ট্র্যাটেজি কনফিগ অনুযায়ী সাজায়:

```
stop = entry - atr × atr_stop_multiplier   (LONG এর জন্য)
target = entry + atr × target_multiple
```

### ৪. ক্যান্ডিডেট ভ্যালিডেশন (`validate_candidate`)
নিচের চেক পাস করতে হয়:

- **min_targets**: কমপক্ষে ১টি টার্গেট (`min_targets: 1`)
- **min_reward_to_risk**: RR ≥ 1.25 (`min_reward_to_risk: 1.25`)

### ৫. আউটকাম রেজিস্টার (`register_outcome`)
পজিশন ক্লোজ হলে:

- Realized R = (exit - entry) / risk_per_unit
- Daily realized R-এ যোগ হয়
- উইন হলে `consecutive_losses = 0`, লস হলে +1
- ৪টি কনসেকিউটিভ লস হলে `kill_switch_active = True`

### ৬. সিম্বল কুলডাউন (`per_symbol_cooldown_minutes: 8`)

একই (venue, symbol, strategy) তে ৮ মিনিটের মধ্যে নতুন সিগন্যাল নয়।

### 📋 রিস্ক সারাংশ (defaults.yaml)

```yaml
risk:
  daily_loss_limit_r: 4                    # দিনে -4R হলে বন্ধ
  kill_switch_after_consecutive_losses: 4  # টানা ৪ লসে কিল সুইচ
  min_reward_to_risk: 1.25                 # সর্বনিম্ন RR 1.25
  min_targets: 1                           # কমপক্ষে ১ টার্গেট
  per_symbol_cooldown_minutes: 8           # প্রতি সিম্বলে ৮ মিনিট কুলডাউন
  max_daily_signals: 200                   # দিনে সর্বোচ্চ ২০০ সিগন্যাল
```

---

## 📲 সিগন্যাল কেমন দেখতে হবে (টেলিগ্রাম মেসেজ বোঝা)

যখন সিগন্যাল ফায়ার হয়, টেলিগ্রামে নিচের মতো মেসেজ আসে:

```
🟢 BTCUSDT · BINANCE · LONG
🎯 Liquidation Cascade Continuation
📈 Regime trending · Weight up-weighted
💎 Confidence 78.4% · Meta 67.2% · RR 4.29R
📍 Entry 67234.5500 · Stop 66990.1200
🏁 TP1 67698.4500 · TP2 68162.3500 · TP3 68162.3500
🧮 Advisory Size 2.40% · Priority 0.842
✅ Filters 21/21
🧠 Why now liquidation burst • range break • delta OI aligned • adverse depth not replenishing • microprice lead
```

### প্রতিটি লাইনের মানে:

| লাইন | মানে |
|------|------|
| `🟢 BTCUSDT · BINANCE · LONG` | সিম্বল = BTCUSDT, ভেন্যু = Binance, দিক = LONG (buy)। 🟢=long, 🔴=short |
| `🎯 Liquidation Cascade Continuation` | কোন স্ট্র্যাটেজি থেকে সিগন্যাল এসেছে |
| `📈 Regime trending · Weight up-weighted` | বর্তমান রেজিম ও সেই রেজিমে স্ট্র্যাটেজিটি up-weighted (1.22x) |
| `💎 Confidence 78.4% · Meta 67.2% · RR 4.29R` | কনফিডেন্স (calibrated), Meta-label prob, Risk:Reward = 4.29R |
| `📍 Entry 67234.5500 · Stop 66990.1200` | এন্ট্রি ও স্টপ লস প্রাইস |
| `🏁 TP1 ... · TP2 ... · TP3 ...` | টেক-প্রফিট লেডার (৩টি টার্গেট) |
| `🧮 Advisory Size 2.40% · Priority 0.842` | ক্যাপিটালের ২.৪% সাইজ, priority score 0.842 (যত বেশি তত ভালো) |
| `✅ Filters 21/21` | ২১টি ভিটো ফিল্টারের সব পাস |
| `🧠 Why now ...` | কেন এই সিগন্যাল — কনফার্মেশন রিজনের লিস্ট |

### অন্যান্য রেজিম ইমোজি:

- 📈 trending
- 🔁 mean_reverting
- ⚠️ high_stress
- 🧭 warmup / unknown

### 🚨 হেলথ অ্যালার্ট

যদি কোনো ভেন্যুর স্বাস্থ্য খারাপ হয় (score < 60), আলাদা মেসেজ আসে:

```
⚠️ Health warning binance
Score 45.3 · p95 380.5ms · stale 12.4s
Reconnects 5 · veto fail rate 18.20% · error rate 5.10%
```

এর মানে বট নিজে বুঝতে পারছে যে বিনান্স কানেকশন খারাপ চলছে।

---

## ⚡ সিগন্যাল কখন ফায়ার হয় (স্টেপ-বাই-স্টেপ)

নিচে একটি সিগন্যাল কখন ফায়ার হয় তার সম্পূর্ণ সিরিয়াল ফ্লো:

### প্রিকন্ডিশন (মাস্ট পাস)

1. ✅ সিম্বলে কমপক্ষে **৩০টি স্ন্যাপশট** জমে গেছে
2. ✅ বটের কিল সুইচ **অফ**
3. ✅ ডেইলি রিয়েলাইজড R **-4R-এর উপরে**
4. ✅ ডেইলি সিগন্যাল কাউন্ট **২০০-এর নিচে**
5. ✅ HMM রেজিম `warmup`-এ নেই

### প্রতিটি স্ক্যানে কী হয়

```
[1] নতুন MarketSnapshot/Trade/LiquidationEvent আসে
        ↓
[2] MarketStateStore-এ সেভ
        ↓
[3] update_open_positions() — আগের পজিশন stop/target হিট হলে ক্লোজ
        ↓
[4] compute_features() — ৪০+ ফিচার তৈরি
        ↓
[5] HMM রেজিম আপডেট
        ↓
[6] build_structural_state() — BOS/CHoCH/FVG/OB/Sweep
        ↓
[7] NewsGuard.assess() — নিউজ ইমপ্যাক্ট
        ↓
[8] historical store-এ ফিচার সেভ
        ↓
[9] DeterministicStrategyEngine.evaluate_all()
    ├─ ১৯টি স্ট্র্যাটেজি সমানে চেক
    └─ যেগুলো পাস করে = candidate সিগন্যাল
        ↓
[10] প্রতিটি candidate-এর জন্য:
     ├─ রেজিম weight চেক (priority_mult ≥ 0.55 মাস্ট)
     ├─ Strategy drift alarm চেক
     ├─ ২১টি ভিটো চেক (সব পাস মাস্ট)
     ├─ Structural contradiction চেক
     ├─ ATR স্টপ ও টার্গেট রিফাইন
     ├─ RR ≥ 1.25 ও targets ≥ 1 ভ্যালিডেশন
     ├─ Kelly advisory size হিসাব
     ├─ Meta-label prob ≥ 0.55
     ├─ Calibrated confidence হিসাব
     ├─ ExposureOptimizer allow চেক (gross + same-dir লিমিট)
     ├─ Cooldown চেক (৮ মিনিট আগে নয়)
     └─ সব পাস → accepted
        ↓
[11] accepted লিস্ট priority_score দিয়ে সর্ট
        ↓
[12] প্রতিটি accepted সিগন্যাল TelegramAlerter.signal_alert()
        ↓
[13] ✅ আপনার টেলিগ্রামে সিগন্যাল পৌঁছায়
```

### 🔥 কখন সিগন্যাল ব্লক হয় (সাপ্রেশন রিজন)

নিচের যেকোনো একটি কারণে candidate সিগন্যাল সাপ্রেস হয় (টেলিগ্রামে যায় না, শুধু লগে থাকে):

| suppressed_reason | মানে |
|-------------------|------|
| `kill_switch_active` | টানা ৪ লসের পর কিল সুইচ অন |
| `daily_hypothetical_loss_limit` | দিনে -4R হয়ে গেছে |
| `daily_signal_cap` | দিনে ২০০ সিগন্যাল শেষ |
| `regime_gate` | রেজিম weight খুব কম (< 0.55) |
| `strategy_drift_alarm` | সাম্প্রতিক ৫০ ট্রেডে উইনরেট খারাপ গেছে |
| `spread_depth_deterioration` | স্প্রেড/ডেপথ খুব খারাপ |
| `wrong_leverage_regime` | continuation কিন্তু OI কমছে, ইত্যাদি |
| `volatility_anomaly` | 5m realized vol 0.15+ |
| `exchange_instability` | mark-index gap বড় বা feed lag |
| `macro_release_window` | FOMC/CPI/NFP টাইম |
| `correlation_spike` | BTC ৩%+ মুভ + altcoin dispersion বেশি |
| `cross_venue_dispersion` | এক্সচেঞ্জগুলোর দাম অনেক আলাদা |
| `stablecoin_liquidity_stress` | USDT/USDC < $0.997 |
| `funding_timestamp_proximity` | ফান্ডিং টাইমের খুব কাছে |
| `liquidation_tape_against_setup` | fade-এর বিপরীতে বড় লিকুইডেশন |
| `news_guard` | NewsGuard সাপ্রেস বলেছে |
| `f01_oi_market_cap_ratio` | OI/mcap > 3% |
| `f02_aggregated_oi_breakout` | OI ব্রেকআউট ছাড়া প্রিমিয়াম বেশি |
| `f03_funding_divergence` | funding dispersion > 3 |
| `f04_cvd_price_divergence` | CVD ও price অনেক আলাদা |
| `f05_liquidation_cluster_proximity` | লিকুইডেশন ক্লাস্টার কাছে না |
| `f06_volatility_regime` | 5m vol > 0.18 |
| `f07_cost_basis_band` | VWAP থেকে > 5 ATR দূরে |
| `f08_etf_basis_regime` | stablecoin stress-এ premium বেশি |
| `f09_depth_imbalance_sanity` | OFI বা depth অস্বাভাবিক |
| `f10_systemic_leverage_composite` | systemic leverage > 1.2 |
| `structural_contradiction` | trend alignment সিগন্যালের বিপরীত |
| `insufficient_targets` | কোনো টার্গেট নেই |
| `reward_to_risk_too_low` | RR < 1.25 |
| `meta_label_rejected` | meta-label prob < 0.55 |
| `portfolio_exposure_limit` | gross/same-dir লিমিট পার হয়ে গেছে |
| `symbol_strategy_cooldown` | ৮ মিনিটের মধ্যে একই সেটআপে সিগন্যাল ছিল |

> বট সাপ্রেস হওয়া সিগন্যাল টেলিগ্রামে পাঠায় না, শুধু লগ ফাইলে লেখে। আপনি চাইলে লগ দেখে বুঝতে পারবেন কোন সেটআপ কেন ব্লক হয়েছে।

---

## 🛠️ ইনস্টল ও রান করার নিয়ম

### প্রিয়ারিকোয়ারমেন্ট

- Python 3.12+
- ইন্টারনেট কানেকশন
- টেলিগ্রাম বট টোকেন (BotFather থেকে)
- (ঐচ্ছিক) FRED API key, Etherscan API key

### স্টেপ ১: ফাইল আনজিপ করুন

```bash
unzip trader_dost_arun_elite_signal_bot.zip
cd trader_dost_arun_elite_signal_bot/rebuild
```

### স্টেপ ২: ভার্চুয়াল এনভায়রনমেন্ট বানান

```bash
python3 -m venv .venv
source .venv/bin/activate       # Linux/Mac
# .venv\Scripts\activate        # Windows
```

### স্টেপ ৩: ডিপেন্ডেন্সি ইনস্টল করুন

```bash
pip install -r requirements.txt
```

এতে ইনস্টল হবে: httpx, websockets, numpy, PyYAML, python-dotenv, scikit-learn, hmmlearn, joblib, beautifulsoup4, pytest, pytest-asyncio, langdetect।

### স্টেপ ৪: এনভায়রনমেন্ট ফাইল সেট করুন

```bash
cp .env.example .env
```

`.env` ফাইল খুলে নিচের মান ভরুন:

```env
BRAND_NAME=Trader Dost Arun Elite
ENVIRONMENT=production
TELEGRAM_BOT_TOKEN=1234567890:ABC...       # BotFather থেকে
TELEGRAM_CHAT_ID=-1001234567890             # আপনার চ্যাট/গ্রুপ ID
FRED_API_KEY=                               # ঐচ্ছিক (economic calendar)
ETHERSCAN_API_KEY=                          # ঐচ্ছিক (whale monitor)
```

### স্টেপ ৫: লোকাল কনফিগ (ঐচ্ছিক)

```bash
cp config/local.example.yaml config/local.yaml
```

`local.yaml`-এ ডিফল্ট সেটিং ওভাররাইড করতে পারেন। যেমন শুধু ৩টি কয়েন ট্র্যাক করতে চাইলে:

```yaml
watchlist:
  binance: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
  bybit: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
  okx: ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
risk:
  per_symbol_cooldown_minutes: 10
  max_daily_signals: 120
```

### স্টেপ ৬: বট চালু করুন

```bash
python app.py
```

বা শর্টকাট স্ক্রিপ্ট দিয়ে:

```bash
bash scripts/run_bot.sh
```

বট চালু হলে লগ দেখবেন — `connected` মেসেজ আসবে প্রতিটি কানেক্টরের জন্য। প্রথম ৩০টি স্ন্যাপশট জমা পর্যন্ত কোনো সিগন্যাল আসবে না।

---

## ⚙️ কনফিগারেশন (defaults.yaml) ব্যাখ্যা

`config/defaults.yaml`-এর প্রতিটি সেকশন ব্যাখ্যা করা হলো:

### `system`
```yaml
system:
  history_size: 3000                      # মেমোরিতে সর্বোচ্চ ৩০০০ স্ন্যাপশট
  min_snapshots_before_signals: 30        # ৩০টি স্ন্যাপশট পর্যন্ত সিগন্যাল নয়
```

### `watchlist`
৫টি এক্সচেঞ্জে কোন কোন সিম্বল ট্র্যাক করবে। প্রতি এক্সচেঞ্জে ১০টি কয়েন (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, ARB)।

### `connectors`
প্রতিটি এক্সচেঞ্জের জন্য আলাদা পোলিং ইন্টারভাল। যেমন Binance OI প্রতি ১৫ সেকেন্ডে, Deribit options প্রতি ৩০ সেকেন্ডে।

### `external`
```yaml
external:
  refresh_seconds: 180        # CoinGecko/DefiLlama/SEC ৩ মিনিটে একবার রিফ্রেশ
```

### `ops`
```yaml
ops:
  health_alert_threshold: 60  # ভেন্যু স্বাস্থ্য ৬০-এর নিচে হলে অ্যালার্ট
```

### `risk` (আগে ব্যাখ্যা করা হয়েছে)

### `adaptive`
```yaml
adaptive:
  kelly_cap: 0.03                       # সর্বোচ্চ ৩% Kelly
  kelly_fraction: 0.5                   # half-Kelly
  hmm_regimes: 3                        # ৩টি রেজিম
  hmm_min_samples: 50                   # ৫০ স্যাম্পল পর্যন্ত warmup
  hmm_refit_seconds: 300                # ৫ মিনিটে রিফিট
  hmm_transition_confirmation_ticks: 3  # ৩ টিক কনফার্মেশন
  meta_label_threshold: 0.55            # meta prob ০.৫৫-এর নিচে রিজেক্ট
  max_gross_exposure: 0.10              # মোট ১০%
  max_same_direction_exposure: 0.06     # একদিকে ৬%
```

### `ml`
```yaml
ml:
  retention_days: 30              # SQLite-এ ৩০ দিন ডেটা রাখে
  walk_forward_embargo: 30        # ৩০ স্যাম্পল embargo
  walk_forward_alpha: 0.0001      # L2 regularization
  calibration_min_samples: 60     # ৬০ স্যাম্পল পর্যন্ত prior ব্যবহার
  prior_mean: 0.55                # prior win rate
  drift_window: 50                # drift চেক ৫০ স্যাম্পল
  drift_alarm_threshold: 0.15     # ১৫% পার্থক্যে alarm
  retrain_max_rows: 1500          # সর্বোচ্চ ১৫০০ রো দিয়ে retrain
  min_rows_for_walk_forward: 100  # ১০০ রো না হলে retrain নয়
```

### `strategy_priors`
১৯টি স্ট্র্যাটেজির prior confidence (0-100)। লাইভে আপডেট হয়।

### `strategies`
প্রতিটি স্ট্র্যাটেজির জন্য `atr_stop_multiplier` ও `target_multiple`। কিছুতে আলাদা থ্রেশহোল্ড আছে।

### `vetoes`
১১টি মূল ভিটোর থ্রেশহোল্ড।

### `futures_filters`
১০টি ফিউচারস-স্পেসিফিক ফিল্টার (F01-F10)।

### `news_guard`
```yaml
news_guard:
  refresh_seconds: 120                        # ২ মিনিটে রিফ্রেশ
  replay_db_path: ./data/news_guard_replay.sqlite3
  semantic_similarity_threshold: 0.72          # ডুপ্লিকেট নিউজ ধরতে
  rss_sources:                                 # SEC press releases
  x_sources:                                   # Binance/OKX-এর X (নিটার)
  telegram_sources:                            # Binance/Hyperliquid announcements
  whale_monitor:                               # Etherscan whale flows
```

---

## 🧪 টেস্ট চালানো

বটের সাথে ৯টি টেস্ট মডিউল আসে:

```bash
pytest -q
```

টেস্ট ফাইলগুলো:

| টেস্ট | কী টেস্ট করে |
|------|-----------|
| `test_adaptive.py` | HMM রেজিম, Kelly, Bayesian, exposure |
| `test_connectors_and_oi.py` | ৫টি কানেক্টর + OI পোলিং |
| `test_elite_upgrade.py` | Elite formatter, RR, TP ladder |
| `test_features.py` | ৪০+ ফিচার হিসাব |
| `test_news_guard.py` | NewsGuard লাইফসাইকেল, সিমিলারিটি |
| `test_regime_weighting.py` | রেজিম ওয়েটিং লজিক |
| `test_signal_engine_outcomes.py` | SignalEngine আউটকাম ট্র্যাকিং |
| `test_structural.py` | BOS/CHoCH/FVG/OB/Sweep |
| `test_vetoes.py` | ২১টি ভিটো চেক |

---

## 🐳 ডিপ্লয়মেন্ট (Docker / systemd)

### Docker দিয়ে চালানো

```bash
docker-compose up -d --build
```

`docker-compose.yml`:
- `trader-dost-elite` নামে কনটেইনার
- `./data` ও `./logs` ভলিউম মাউন্ট
- `.env` ফাইল অটো-লোড
- `restart: unless-stopped` (ক্র্যাশ হলে অটো-রিস্টার্ট)

### systemd দিয়ে চালানো (লিনাক্স সার্ভার)

```bash
# /opt/trader-dost-elite-এ কোড রাখুন
sudo cp systemd/trader-dost-elite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trader-dost-elite
sudo systemctl start trader-dost-elite

# লগ দেখতে
journalctl -u trader-dost-elite -f
```

`systemd/trader-dost-elite.service`:
- `Restart=always`, `RestartSec=10` — ক্র্যাশ হলে ১০ সেকেন্ডে রিস্টার্ট
- `User=ubuntu` — নন-রুট ইউজার
- `EnvironmentFile=.env` — এনভায়রনমেন্ট লোড

---

## ❓ প্রায়শই জিজ্ঞাসিত প্রশ্ন (FAQ)

### Q1: বট কি নিজে ট্রেড করে?
**না**। এটি শুধু সিগন্যাল পাঠায় টেলিগ্রামে। ট্রেড আপনাকে নিজে ম্যানুয়ালি নিতে হবে।

### Q2: কত সময় পর পর সিগন্যাল আসে?
নির্দিষ্ট নয়। সব ফিল্টার পাস হলে আসে। মার্কেট শান্ত থাকলে ঘণ্টায় ১-২টি, ভোলাটাইল থাকলে ১০-২০টি পর্যন্ত।

### Q3: প্রতিটি সিগন্যাল কি লাভজনক?
**না**। এটি কোনো ম্যাজিক বট নয়। Bayesian + ML দিয়ে এডজি ধরার চেষ্টা করে, কিন্তু কোনো গ্যারান্টি নেই। নিজের রিস্ক ম্যানেজমেন্ট করে নেবেন।

### Q4: কোন সিগন্যালে বিশ্ব করব?
`priority_score` বেশি হলে (০.৭+) সেটি বেশি বিশ্বস্ত। কনফিডেন্স ৬০%+ ও RR ২R+ হলে ভালো।

### Q5: কুলডাউন কেন?
একই সিম্বলে একই স্ট্র্যাটেজি ৮ মিনিটের মধ্যে আবার সিগন্যাল দেওয়া বন্ধ করে, যাতে over-trading না হয়।

### Q6: Kill switch কখন অন হয়?
টানা ৪টি লস ট্রেড হলে বা দিনে -4R হলে। পরের দিন UTC রিসেটে অফ হয়।

### Q7: Meta-label prob কী?
একটি ML মডেল যা বলে "এই সেটআপে জেতার সম্ভাবনা কত"। ০.৫৫-এর নিচে হলে সিগন্যাল রিজেক্ট করে।

### Q8: কোন API key গুরুত্বপূর্ণ?
- **টেলিগ্রাম বট টোকেন + চ্যাট ID**: মাস্ট
- **FRED API**: ম্যাক্রো ক্যালেন্ডার চাইলে
- **Etherscan API**: হোয়েল ফ্লো মনিটর চাইলে

### Q9: বট কত RAM খায়?
প্রায় ৫০টি WebSocket + ৫০টি সিম্বলের মেমোরি স্টোর = ৫০০MB–১GB।

### Q10: লগ কোথায় থাকে?
`logs/` ফোল্ডারে (Docker/systemd-এ মাউন্ট করা)।

### Q11: একাধিক সিগন্যাল একসাথে আসলে?
হ্যাঁ, একই সিম্বলে একাধিক স্ট্র্যাটেজি পাস করতে পারে। priority_score অনুযায়ী টেলিগ্রামে যায়।

### Q12: বট কি backtest করতে পারে?
সরাসরি না। তবে `data/historical.sqlite3`-এ ফিচার ও আউটকাম জমে, পরে walk-forward দিয়ে মডেল retrain হয়।

---

## ⚠️ সতর্কতা ও ডিসক্লেইমার

1. **এই বট কোনো আর্থিক পরামর্শ নয়।** ক্রিপ্টো ফিউচারস ট্রেডিং অত্যন্ত ঝুঁকিপূর্ণ।
2. **সিগন্যাল লাভজনক হবে এমন কোনো গ্যারান্টি নেই।** ML মডেল অতীত ডেটা থেকে শেখে, ভবিষ্যৎ বলে না।
3. **সবসময় নিজের রিস্ক ম্যানেজমেন্ট করুন।** Kelly advisory size শুধু সাজেশন, বাধ্যবাধকতা নয়।
4. **প্রথমে পেপার ট্রেড করুন।** সিগন্যাল কেমন আসছে দেখে তারপর রিয়েল ট্রেড।
5. **API key গোপন রাখুন।** `.env` ফাইল git-এ commit করবেন না।
6. **মার্কেট ক্র্যাশে সব মডেল ভুল করে।** HMM high_stress রেজিম এমন সময় ধরতে চেষ্টা করে, কিন্তু সবসময় সঠিক নয়।
7. **স্টপ লস সবসময় মানুন।** সিগন্যালে দেওয়া stop প্রাইস ছাড়িলে ক্লোজ করুন।
8. **লিভারেজ কম রাখুন।** ফিউচারসে ২-৩x এর বেশি না।
9. **ট্রেড সাইজ ১-২% এর বেশি না।** Kelly ৩% বললেও ১-২% রাখুন।
10. **বট ২৪/৭ চালু রাখুন।** বন্ধ থাকলে সিগন্যাল মিস হবে। Docker/systemd ব্যবহার করুন।

---

## 🎁 Bonus: ট্রেড নেওয়ার চেকলিস্ট

সিগন্যাল পেলে ট্রেড নেওয়ার আগে এই চেকলিস্ট মানুন:

- [ ] Confidence ৬০%+ ?
- [ ] Meta prob ৬০%+ ?
- [ ] RR অন্তত ১.৫R ?
- [ ] রেজিম স্ট্র্যাটেজির সাথে মেলে? (trending → continuation, mean_reverting → reversion)
- [ ] কনফার্মেশন লিস্ট পড়েছেন?
- [ ] এই সিম্বলে আগে কোনো পজিশন আছে?
- [ ] ডেইলি লস লিমিটের মধ্যে আছেন?
- [ ] স্টপ লস কোথায় রাখবেন জানেন?
- [ ] TP1, TP2, TP3 কোথায় বুঝেছেন?
- [ ] পজিশন সাইজ ১-২% এর মধ্যে?

---

## 📞 সাপোর্ট

কোনো সমস্যা হলে:

1. লগ ফাইল চেক করুন (`logs/` ফোল্ডার)
2. `pytest -q` দিয়ে টেস্ট রান করে দেখুন
3. `.env` ফাইল ঠিকমতো ভরা আছে কিনা চেক করুন
4. টেলিগ্রাম বট টোকেন সঠিক কিনা চেক করুন
5. ইন্টারনেট কানেকশন ঠিক আছে কিনা দেখুন

---

**শুভকামনা! 🚀** এই বট একটি শক্তিশালী tool, কিন্তু সফলতা নির্ভর করে আপনার নিজের ডিসিপ্লিন ও রিস্ক ম্যানেজমেন্টের উপর। ট্রেড করার আগে পুরো গাইডটি আরেকবার পড়ুন।
