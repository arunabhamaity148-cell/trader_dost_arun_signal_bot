import asyncio
from datetime import timedelta

import pytest

from app import SignalEvaluationScheduler
from trader_dost_arun.core.models import FeatureSet, MarketSnapshot, OrderBookLevel, utc_now
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.ops.health import HealthScorer
from trader_dost_arun.signals.vetoes import VetoEngine

CONFIG = {
    "vetoes": {
        "exchange_instability": {"max_mark_index_gap_bps": 1000, "max_feed_lag_seconds": 2},
        "freshness_quorum": {"min_sources": 2},
        "volatility_anomaly": {"rv_5m_max": 1.0},
        "correlation_spike": {"dispersion_limit": 9999},
        "cross_venue_dispersion": {"price_dispersion_limit": 9999, "premium_dispersion_limit": 9999},
        "funding_proximity": {"pre_minutes": 5, "post_minutes": 3},
        "liquidation_tape": {"liquidation_notional_limit": 999999999},
    }
}


def _snapshot(venue: str, symbol: str, age_seconds: float) -> MarketSnapshot:
    ts = utc_now() - timedelta(seconds=age_seconds)
    return MarketSnapshot(
        venue=venue,
        symbol=symbol,
        event_time=ts,
        arrival_time=ts,
        bid_levels=[OrderBookLevel(99, 10)],
        ask_levels=[OrderBookLevel(101, 12)],
        mark_price=100,
        index_price=100,
        funding_rate=0.0001,
        open_interest=1000,
        premium=0.0,
        spread=2.0,
    )


def test_stale_snapshot_blocks_and_recovery_restores_freshness():
    state = MarketStateStore()
    state.add_snapshot(_snapshot("binance", "BTCUSDT", 0.2))
    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 5.0))
    features = FeatureSet("binance", "BTCUSDT", utc_now(), {"spread": 1, "same_side_depth": 100, "atr": 10, "delta_oi": 1, "funding_zscore": 0, "realized_vol_5m": 0.05, "mark_price": 100, "index_price": 100, "price_dispersion": 0, "premium_dispersion": 0, "liquidation_notional": 0})
    engine = VetoEngine(CONFIG)
    checks, failed = engine.evaluate("order_flow_imbalance_continuation", "binance", "BTCUSDT", features, type("S", (), {"trend_alignment": None})(), state, ExternalContext(), {})
    assert checks["stale_snapshot"] is False
    assert failed == "stale_snapshot"

    state.add_snapshot(_snapshot("okx", "BTC-USDT-SWAP", 0.1))
    checks, failed = engine.evaluate("order_flow_imbalance_continuation", "binance", "BTCUSDT", features, type("S", (), {"trend_alignment": None})(), state, ExternalContext(), {})
    assert checks["stale_snapshot"] is True
    assert failed is None


def test_health_scorer_classifies_startup_warmup_healthy_and_degraded():
    scorer = HealthScorer(min_samples_for_healthy=5, stale_seconds_for_degraded=5)
    assert scorer.score("binance", {"p50": 0, "p95": 0, "p99": 0, "stale": 999, "reconnects": 0, "errors": 0, "sample_count": 0}, 0).status == "starting"
    assert scorer.score("binance", {"p50": 1, "p95": 1, "p99": 1, "stale": 1, "reconnects": 0, "errors": 0, "sample_count": 2}, 0).status == "warmup"
    assert scorer.score("binance", {"p50": 1, "p95": 2, "p99": 3, "stale": 1, "reconnects": 0, "errors": 0, "sample_count": 10}, 0).status == "healthy"
    assert scorer.score("binance", {"p50": 1, "p95": 2, "p99": 3, "stale": 6, "reconnects": 0, "errors": 0, "sample_count": 10}, 0).status == "degraded"


@pytest.mark.asyncio
async def test_signal_scheduler_coalesces_hot_events_and_stops_cleanly():
    calls = []

    async def callback(venue: str, symbol: str) -> None:
        calls.append((venue, symbol))
        await asyncio.sleep(0.05)

    scheduler = SignalEvaluationScheduler(callback, min_interval_seconds=0.05, max_concurrent=1)
    await scheduler.start()
    for _ in range(10):
        scheduler.notify("binance", "BTCUSDT")
    await asyncio.sleep(0.18)
    await scheduler.stop()
    assert 1 <= len(calls) <= 3
    assert all(call == ("binance", "BTCUSDT") for call in calls)
