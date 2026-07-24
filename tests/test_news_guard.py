from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def test_news_guard_measures_real_market_reaction(tmp_path: Path):
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
    assessment = guard.assess("BTCUSDT", "binance", None, state, ExternalContext(), "high_stress")
    observed = guard.events[event.event_id].observed_impact
    assert assessment.active_events
    assert observed.price_change_bps > 0
    assert observed.open_interest_change_pct > 0
    assert observed.funding_change_bps > 0
