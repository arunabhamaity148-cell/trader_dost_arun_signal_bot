from datetime import datetime, timezone

from trader_dost_arun.core.models import Direction, MarketSnapshot, OrderBookLevel, Trade
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.features.calculations import compute_features


def _snapshot(px: float) -> MarketSnapshot:
    return MarketSnapshot(
        venue="binance",
        symbol="BTCUSDT",
        event_time=datetime.now(timezone.utc),
        bid_levels=[OrderBookLevel(px - 1, 10), OrderBookLevel(px - 2, 8)],
        ask_levels=[OrderBookLevel(px + 1, 7), OrderBookLevel(px + 2, 6)],
        mark_price=px,
        index_price=px - 0.5,
        funding_rate=0.001,
        open_interest=100000,
        premium=0.5,
        spread=2,
    )


def test_feature_computation_contains_core_metrics():
    state = MarketStateStore()
    for i in range(40):
        state.add_snapshot(_snapshot(100 + i))
        state.add_trade(Trade("binance", "BTCUSDT", 100 + i, 2, Direction.LONG if i % 2 == 0 else Direction.SHORT, datetime.now(timezone.utc)))
    view = state.view("binance", "BTCUSDT")
    features = compute_features(view, {"binance": view})
    assert "order_book_imbalance" in features.values
    assert features.get("session_vwap") > 0
    assert features.get("open_interest") > 0
