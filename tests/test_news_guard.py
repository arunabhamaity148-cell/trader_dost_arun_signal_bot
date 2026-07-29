from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncio

from trader_dost_arun.core.models import MarketSnapshot, OrderBookLevel
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.newsguard.guard import NewsGuard
from trader_dost_arun.newsguard.models import NewsEvent


def snapshot(px: float, oi: float, funding: float, when: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        venue="binance",
        symbol="BTCUSDT",
        event_time=when,
        bid_levels=[OrderBookLevel(px - 1, 10)],
        ask_levels=[OrderBookLevel(px + 1, 10)],
        mark_price=px,
        index_price=px,
        funding_rate=funding,
        open_interest=oi,
        premium=0.0,
        spread=2.0,
    )


async def test_news_guard_measures_real_market_reaction(tmp_path: Path):
    cfg = {"news_guard": {"replay_db_path": str(tmp_path / "replay.sqlite3")}}
    guard = NewsGuard(cfg)
    event = NewsEvent(
        event_id="evt1",
        title="BTC exchange incident",
        summary="BTC withdrawals halted",
        url="https://example.com/evt1",
        source_type="rss",
        source_name="test",
        category="incident",
        severity=0.95,
        sentiment=-1.0,
        language="en",
        symbols=["BTC"],
        entities=["BTC"],
        first_seen_at=datetime.now(timezone.utc) - timedelta(hours=3),
        last_seen_at=datetime.now(timezone.utc) - timedelta(hours=2),
        lifecycle="peak",
    )
    guard.events[event.event_id] = event
    state = MarketStateStore()
    base = datetime.now(timezone.utc) - timedelta(minutes=6)
    prices = [100, 101, 102, 108, 109, 110]
    ois = [1_000, 1_010, 1_015, 1_100, 1_120, 1_130]
    funds = [0.0001, 0.0001, 0.00011, 0.0002, 0.00022, 0.00024]
    for i in range(6):
        state.add_snapshot(snapshot(prices[i], ois[i], funds[i], base + timedelta(minutes=i)))
    assessment = await guard.assess("BTCUSDT", "binance", None, state, ExternalContext(), "high_stress")
    observed = guard.events[event.event_id].observed_impact
    assert assessment.active_events
    assert observed.price_change_bps > 0
    assert observed.open_interest_change_pct > 0
    assert observed.funding_change_bps > 0


async def test_assess_survives_concurrent_event_merges(tmp_path: Path):
    """Regression test for RuntimeError: dictionary changed size during
    iteration, seen in production when many per-symbol signal-evaluation
    tasks called assess() concurrently while the news-refresh loop merged
    new events into guard.events. assess()/observe_market() now take the
    same asyncio.Lock as event merging, so this must never raise."""
    cfg = {"news_guard": {"replay_db_path": str(tmp_path / "replay.sqlite3")}}
    guard = NewsGuard(cfg)
    state = MarketStateStore()

    def make_event(i) -> NewsEvent:
        now = datetime.now(timezone.utc)
        return NewsEvent(
            event_id=f"evt-{i}", title=f"event {i}", summary="stress",
            url=f"https://example.com/{i}", source_type="rss", source_name="stress",
            category="incident", severity=0.5, sentiment=0.0, language="en",
            symbols=["BTC", "ETH", "ADA", "LINK"], entities=[],
            first_seen_at=now, last_seen_at=now,
        )

    async def assess_worker(symbol: str):
        for _ in range(100):
            await guard.assess(symbol, "bybit", None, state, ExternalContext(), "high_stress")

    async def merge_worker(offset: int):
        for i in range(100):
            await guard._merge_event_async(make_event(f"{offset}-{i}"))

    symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "LINKUSDT"]
    await asyncio.gather(
        *(assess_worker(symbol) for symbol in symbols),
        *(merge_worker(offset) for offset in range(4)),
    )
