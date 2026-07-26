from datetime import timedelta

from trader_dost_arun.core.models import MarketSnapshot, OrderBookLevel, utc_now
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.core.symbols import normalize_instrument


def _snapshot(venue: str, symbol: str, price: float, age_seconds: float = 0.0) -> MarketSnapshot:
    when = utc_now() - timedelta(seconds=age_seconds)
    return MarketSnapshot(
        venue=venue,
        symbol=symbol,
        event_time=when,
        arrival_time=when,
        bid_levels=[OrderBookLevel(price - 1, 10)],
        ask_levels=[OrderBookLevel(price + 1, 12)],
        mark_price=price,
        index_price=price,
        funding_rate=0.0001,
        open_interest=1000,
        premium=0.0,
        spread=2.0,
    )


def test_symbol_normalization_groups_perpetual_aliases_but_not_options():
    linear = normalize_instrument("binance", "BTCUSDT")
    swap = normalize_instrument("okx", "BTC-USDT-SWAP")
    perp = normalize_instrument("hyperliquid", "BTC-PERP")
    option = normalize_instrument("deribit", "BTC-30AUG26-60000-C")
    assert linear.canonical_symbol == swap.canonical_symbol == perp.canonical_symbol
    assert option.canonical_symbol != perp.canonical_symbol


def test_peer_views_resolve_cross_venue_aliases():
    state = MarketStateStore()
    state.add_snapshot(_snapshot("binance", "BTCUSDT", 100))
    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 101))
    state.add_snapshot(_snapshot("hyperliquid", "BTC-PERP", 99))
    peers = state.peer_views("BTCUSDT", "binance")
    assert set(peers) == {"binance", "okx", "hyperliquid"}


def test_cross_venue_freshness_quorum_and_recovery():
    state = MarketStateStore()
    state.add_snapshot(_snapshot("binance", "BTCUSDT", 100, age_seconds=0.2))
    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 101, age_seconds=0.3))
    state.add_snapshot(_snapshot("hyperliquid", "BTC-PERP", 99, age_seconds=9.0))
    fresh = state.freshness("binance", "BTCUSDT", max_age_seconds=2.0, min_sources=2)
    assert fresh.quorum_met is True
    assert fresh.stale_sources == {"hyperliquid": fresh.stale_sources["hyperliquid"]}

    state = MarketStateStore()
    state.add_snapshot(_snapshot("binance", "BTCUSDT", 100, age_seconds=0.2))
    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 101, age_seconds=9.0))
    degraded = state.freshness("binance", "BTCUSDT", max_age_seconds=2.0, min_sources=2)
    assert degraded.quorum_met is False

    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 101, age_seconds=0.1))
    recovered = state.freshness("binance", "BTCUSDT", max_age_seconds=2.0, min_sources=2)
    assert recovered.quorum_met is True
    assert "okx" in recovered.fresh_sources
