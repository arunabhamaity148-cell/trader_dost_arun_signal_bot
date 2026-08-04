import pytest

from datetime import datetime, timedelta, timezone

from trader_dost_arun.core.models import Direction, HypotheticalPosition, MarketSnapshot, OrderBookLevel, Signal, Trade
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.signals.engine import SignalEngine

CONFIG = {
    "risk": {"daily_loss_limit_r": 4, "kill_switch_after_consecutive_losses": 4},
    "adaptive": {
        "kelly_cap": 0.03,
        "kelly_fraction": 0.5,
        "hmm_regimes": 3,
        "hmm_min_samples": 5,
        "hmm_refit_seconds": 9999,
        "hmm_transition_confirmation_ticks": 1,
        "meta_label_threshold": 0.4,
        "max_gross_exposure": 1.0,
        "max_same_direction_exposure": 1.0,
    },
    "strategy_priors": {
        "liquidation_cascade_continuation": 92,
        "extreme_funding_crowding_reversion": 90,
        "order_flow_imbalance_continuation": 89,
        "aggressor_exhaustion_absorption_fade": 86,
        "fresh_oi_breakout_continuation": 84,
        "single_venue_premium_snapback": 82,
        "cross_venue_basis_dispersion_convergence": 80,
        "spot_index_lead_follow_through": 78,
        "funding_window_inventory_rebalance": 74,
        "deribit_iv_shock_repricing": 71,
    },
    "strategies": {
        "liquidation_cascade_continuation": {"atr_stop_multiplier": 0.7, "target_multiple": 3.0},
        "aggressor_exhaustion_absorption_fade": {"cvd_extreme": 1000, "atr_stop_multiplier": 1.0},
    },
    "vetoes": {
        "volatility_anomaly": {"rv_5m_max": 1.0},
        "exchange_instability": {"max_mark_index_gap_bps": 1000, "max_feed_lag_seconds": 999},
        "correlation_spike": {"dispersion_limit": 9999},
        "cross_venue_dispersion": {"price_dispersion_limit": 9999, "premium_dispersion_limit": 9999},
        "funding_proximity": {"pre_minutes": 5, "post_minutes": 3},
        "liquidation_tape": {"liquidation_notional_limit": 999999999},
    },
}


def snapshot(px: float, oi: float, when: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        venue="binance",
        symbol="BTCUSDT",
        event_time=when,
        bid_levels=[OrderBookLevel(px - 1, 15), OrderBookLevel(px - 2, 12)],
        ask_levels=[OrderBookLevel(px + 1, 5), OrderBookLevel(px + 2, 5)],
        mark_price=px,
        index_price=px - 0.5,
        funding_rate=0.0002,
        open_interest=oi,
        premium=0.5,
        spread=2,
    )


@pytest.mark.asyncio
async def test_position_monitor_updates_learning_components():
    state = MarketStateStore()
    start = datetime.now(timezone.utc) - timedelta(minutes=20)
    for i in range(12):
        ts = start + timedelta(minutes=i)
        px = 100 + i
        state.add_snapshot(snapshot(px, 1_000 + i * 25, ts))
        state.add_trade(Trade("binance", "BTCUSDT", px, 20, Direction.LONG, ts))
    engine = SignalEngine(CONFIG)
    signal = Signal(
        strategy_name="liquidation_cascade_continuation",
        symbol="BTCUSDT",
        venue="binance",
        direction=Direction.LONG,
        entry=110.0,
        stop=108.0,
        targets=[114.0],
        confidence=75.0,
        advisory_size_fraction=0.01,
        regime="trending",
        confirmations=["liquidation burst"],
        vetoes_checked={"news_guard": True},
        metadata={
            "feature_row": [1.0, 2.0, 3.0, 4.0, 0.5, 1.2],
            "feature_map": {"spread": 2.0, "delta_oi": 50.0, "realized_vol_1m": 0.2},
        },
    )
    engine.exposure.add_position(HypotheticalPosition(signal=signal))
    state.add_snapshot(snapshot(115.0, 1_400, datetime.now(timezone.utc)))
    closed = await engine.update_open_positions("binance", "BTCUSDT", state)
    assert closed
    assert state.performances[closed[0].signal.strategy_name].sample_size == 1
    assert engine.meta._is_fitted is True
    assert engine.importance.summary()
    assert not engine.exposure.positions
