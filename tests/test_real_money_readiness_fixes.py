"""Regression tests for three real-money-readiness gaps:

1. Risk-engine kill switch / daily loss state silently reset on every
   restart because it was written to checkpoint.json but never read back.
2. Missing market data (failed REST fetches) silently defaulted to 0.0 and
   was indistinguishable from a genuine zero reading in veto checks.
3. Strategy win-rate/payoff-ratio reset to a fake neutral prior on every
   restart even though real closed-trade history was in SQLite already.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trader_dost_arun.core.models import Direction, FeatureSet, HypotheticalPosition, Signal, StructuralState
from trader_dost_arun.core.persistence import PositionStore
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.risk.engine import RiskEngine
from trader_dost_arun.signals.vetoes import VetoEngine

CONFIG = {
    "risk": {"daily_loss_limit_r": 4, "kill_switch_after_consecutive_losses": 4},
    "vetoes": {
        "exchange_instability": {"max_feed_lag_seconds": 2, "max_mark_index_gap_bps": 50},
        "volatility_anomaly": {"rv_5m_max": 0.5},
        "correlation_spike": {"dispersion_limit": 1.0},
        "cross_venue_dispersion": {"price_dispersion_limit": 1.0, "premium_dispersion_limit": 1.0},
        "funding_proximity": {"pre_minutes": 5, "post_minutes": 5},
        "liquidation_tape": {"liquidation_notional_limit": 1_000_000},
        "freshness_quorum": {"min_sources": 1},
    },
}


# ---------------------------------------------------------------------------
# Fix 1: risk state persists and reloads across a restart
# ---------------------------------------------------------------------------

def test_kill_switch_active_state_survives_restore_same_day():
    risk = RiskEngine(CONFIG)
    risk.consecutive_losses = 4
    risk.kill_switch_active = True
    risk.daily_realized_r = -3.5
    saved = {
        "day": datetime.now(timezone.utc).date().isoformat(),
        "daily_realized_r": risk.daily_realized_r,
        "daily_slippage_cost": 0.2,
        "consecutive_losses": risk.consecutive_losses,
        "kill_switch_active": risk.kill_switch_active,
    }

    # Simulate a fresh process starting up after a crash/restart.
    restarted = RiskEngine(CONFIG)
    assert restarted.kill_switch_active is False  # sanity: fresh engine starts clean
    restarted.restore_state(saved)

    assert restarted.kill_switch_active is True
    assert restarted.consecutive_losses == 4
    assert restarted.daily_realized_r == -3.5
    allowed, reason = restarted.allow_new_signal()
    assert allowed is False
    assert reason == "kill_switch_active"


def test_kill_switch_latch_survives_day_boundary_but_daily_pnl_resets():
    """Fix (hardening pass): the kill switch / consecutive-loss counter are a
    LATCH. They must survive BOTH a restart AND the UTC day boundary - otherwise
    a bot that tripped its loss brake at 23:59 silently resumes at 00:01 with no
    operator action. Only the day-scoped PnL accumulators reset at the boundary.
    """
    stale_saved = {
        "day": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
        "daily_realized_r": -10.0,
        "consecutive_losses": 9,
        "kill_switch_active": True,
    }
    risk = RiskEngine(CONFIG)
    risk.restore_state(stale_saved)
    # Day-scoped PnL from a previous day is discarded ...
    assert risk.daily_realized_r == 0.0
    assert risk.daily_slippage_cost == 0.0
    # ... but the tripped brake and the streak that caused it carry over and
    # stay engaged until an operator explicitly resets them.
    assert risk.kill_switch_active is True
    assert risk.consecutive_losses == 9
    allowed, reason = risk.allow_new_signal()
    assert allowed is False and reason == "kill_switch_active"


def test_kill_switch_latch_requires_operator_reset_to_clear():
    risk = RiskEngine(CONFIG)
    risk.consecutive_losses = CONFIG["risk"]["kill_switch_after_consecutive_losses"]
    position = _make_position("alpha")
    position.signal.direction = Direction.LONG
    position.fill_price = position.signal.entry
    position.signal.stop = position.signal.entry - 1.0
    # A losing close engages the kill switch.
    risk.register_outcome(position, exit_price=position.signal.entry - 2.0)
    assert risk.kill_switch_active is True
    # Simulated day boundary: PnL resets, latch stays engaged.
    risk.maybe_reset()
    risk.last_reset_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    risk.maybe_reset()
    assert risk.kill_switch_active is True  # midnight does NOT clear it
    assert risk.daily_realized_r == 0.0     # but the daily accumulator does reset
    # Operator reset clears it.
    risk.reset_kill_switch()
    assert risk.kill_switch_active is False
    assert risk.consecutive_losses == 0


def test_restore_state_handles_empty_checkpoint_gracefully():
    risk = RiskEngine(CONFIG)
    risk.restore_state({})
    assert risk.kill_switch_active is False
    allowed, _ = risk.allow_new_signal()
    assert allowed is True


# ---------------------------------------------------------------------------
# Fix 2: missing data must veto, not silently pass as a real zero reading
# ---------------------------------------------------------------------------

def _base_features(missing: frozenset[str] = frozenset()) -> FeatureSet:
    return FeatureSet(
        "binance", "BTCUSDT", datetime.now(timezone.utc),
        values={
            "spread": 1, "same_side_depth": 100, "atr": 10, "delta_oi": 0,
            "funding_zscore": 0, "premium_zscore": 0, "funding_rate": 0,
            "realized_vol_5m": 0.05, "mark_price": 110, "index_price": 100,
            "price_dispersion": 0, "premium_dispersion": 0, "liquidation_notional": 0,
        },
        missing=missing,
    )


def test_missing_open_interest_vetoes_reversion_strategy_that_reads_delta_oi():
    vetoes = VetoEngine(CONFIG)
    structural = StructuralState()
    state = MarketStateStore()
    # delta_oi genuinely missing (REST fetch never succeeded) - the strategy
    # would otherwise read the 0.0 default as "flat/bearish" and pass.
    features = _base_features(missing=frozenset({"delta_oi"}))
    checks, failed = vetoes.evaluate(
        "extreme_funding_crowding_reversion", "binance", "BTCUSDT", features, structural, state,
        external=_FakeExternal(), peer_features={},
    )
    assert failed == "data_completeness"
    assert checks["data_completeness"] is False


def test_complete_data_does_not_trigger_data_completeness_veto():
    vetoes = VetoEngine(CONFIG)
    structural = StructuralState()
    state = MarketStateStore()
    features = _base_features()  # nothing missing
    checks, failed = vetoes.evaluate(
        "extreme_funding_crowding_reversion", "binance", "BTCUSDT", features, structural, state,
        external=_FakeExternal(), peer_features={},
    )
    assert checks["data_completeness"] is True
    assert failed != "data_completeness"


def test_missing_mark_or_index_price_vetoes_every_strategy():
    vetoes = VetoEngine(CONFIG)
    structural = StructuralState()
    state = MarketStateStore()
    features = _base_features(missing=frozenset({"mark_price"}))
    checks, failed = vetoes.evaluate(
        "liquidation_cascade_continuation", "binance", "BTCUSDT", features, structural, state,
        external=_FakeExternal(), peer_features={},
    )
    assert failed == "data_completeness"


class _FakeExternal:
    macro_blocked = False
    sec_blocked = False
    stablecoin_stress = False
    benchmark_returns: dict = {}


# ---------------------------------------------------------------------------
# Fix 3: strategy performance rebuilds from real trade history on startup
# ---------------------------------------------------------------------------

def _make_position(strategy_name: str) -> HypotheticalPosition:
    signal = Signal(
        strategy_name=strategy_name, symbol="BTCUSDT", venue="binance",
        direction=Direction.LONG, entry=100.0, stop=98.0, targets=[104.0],
        confidence=75.0, advisory_size_fraction=0.01, regime="trending",
        confirmations=[], vetoes_checked={}, created_at=datetime.now(timezone.utc),
    )
    return HypotheticalPosition(signal=signal)


def test_performance_rebuilds_from_position_store_history_not_neutral_prior(tmp_path: Path):
    store = PositionStore(tmp_path / "positions.sqlite3")
    # Two wins, one loss for "alpha" from a previous session.
    store.save_position(_make_position("alpha"))
    store.close_position("BTCUSDT", "binance", 104.0, realized_r=2.0, exit_reason="target")
    store.save_position(_make_position("alpha"))
    store.close_position("BTCUSDT", "binance", 104.0, realized_r=1.5, exit_reason="target")
    store.save_position(_make_position("alpha"))
    store.close_position("BTCUSDT", "binance", 98.0, realized_r=-1.0, exit_reason="stop")

    state = MarketStateStore()
    # Before rebuild: fresh process, no in-memory history yet.
    assert state.performances["alpha"].sample_size == 0
    assert state.performances["alpha"].win_rate == 0.5  # neutral prior only until rebuilt

    state.rebuild_performance_from_history(store.get_closed_realized_r_by_strategy())

    perf = state.performances["alpha"]
    assert perf.sample_size == 3
    assert perf.wins == 2
    assert perf.losses == 1
    assert abs(perf.win_rate - (2 / 3)) < 1e-9


def test_rebuild_with_no_history_leaves_neutral_prior_untouched():
    state = MarketStateStore()
    state.rebuild_performance_from_history({})
    assert state.performances["alpha"].sample_size == 0
    assert state.performances["alpha"].win_rate == 0.5


# ---------------------------------------------------------------------------
# Fix 4 (found during continued audit): closing one strategy's position must
# not corrupt or close another strategy's concurrent position on the same
# symbol+venue.
# ---------------------------------------------------------------------------

def test_exposure_close_position_does_not_affect_other_strategy_same_symbol(tmp_path: Path):
    from trader_dost_arun.adaptive.exposure import ExposureOptimizer

    store = PositionStore(tmp_path / "positions.sqlite3")
    exposure = ExposureOptimizer(max_gross_exposure=1.0, max_same_direction=1.0, position_store=store)

    pos_a = _make_position("alpha")
    pos_b = _make_position("beta")
    exposure.add_position(pos_a)
    exposure.add_position(pos_b)
    assert pos_a.db_id is not None and pos_b.db_id is not None and pos_a.db_id != pos_b.db_id

    pos_a.closed_at = datetime.now(timezone.utc)
    pos_a.exit_price = 104.0
    pos_a.realized_r_multiple = 2.0
    pos_a.exit_reason = "target"
    exposure.close_position(pos_a)

    # Only pos_a should be gone from the in-memory open list.
    assert pos_a not in exposure.positions
    assert pos_b in exposure.positions

    # beta's row in SQLite must remain untouched.
    history = {row["strategy_name"]: row for row in store.get_history(limit=10)}
    assert history["alpha"]["realized_r"] == 2.0
    assert history["beta"]["closed_at"] is None
    assert history["beta"]["realized_r"] is None



# ---------------------------------------------------------------------------
# Fix 5 (found during continued audit): Telegram delivery failures must be
# detectable, not silent.
# ---------------------------------------------------------------------------

def test_telegram_send_failure_is_tracked_not_silent(tmp_path: Path):
    import asyncio as _asyncio
    from trader_dost_arun.ops.alerts import TelegramAlerter

    async def _run():
        alerter = TelegramAlerter(token="", chat_id="", counter_db=tmp_path / "counter.sqlite3")
        # No token/chat id configured - send() must report False, not just log.
        delivered = await alerter.send("test message")
        assert delivered is False
        return alerter

    alerter = _asyncio.run(_run())
    # Unconfigured Telegram is a config issue, not a transient failure -
    # it must not be counted toward the consecutive-failure escalation.
    assert alerter.consecutive_send_failures == 0


def test_signal_alert_reports_failed_when_send_raises(tmp_path: Path):
    import asyncio as _asyncio
    from trader_dost_arun.ops.alerts import TelegramAlerter

    async def _run():
        alerter = TelegramAlerter(token="fake-token", chat_id="123", counter_db=tmp_path / "counter.sqlite3")

        async def _fails(*_a, **_kw):
            return False

        alerter.send = _fails
        result = await alerter.signal_alert(_make_position("alpha").signal)
        return alerter, result

    alerter, result = _asyncio.run(_run())
    assert result == "failed"
    assert alerter.total_signal_alerts_failed == 1
    assert alerter.total_signal_alerts_sent == 0


# ---------------------------------------------------------------------------
# Fix 6 (found during continued audit): 429 rate limits must be tracked
# separately from generic transient errors, with a dedicated venue-wide
# cooldown.
# ---------------------------------------------------------------------------

def test_rate_limit_tracked_separately_from_generic_failures():
    import asyncio as _asyncio
    import logging as _logging
    import httpx as _httpx
    from trader_dost_arun.data.base import SharedHttpResources, BasePublicConnector

    resources = SharedHttpResources(client=None, semaphore=_asyncio.Semaphore(1))

    class _FakeConnector:
        venue = "binance"
        symbol = "group-1"
        config: dict = {}

        def __init__(self):
            self._http_resources = resources
            self.logger = _logging.getLogger("test")

    connector = _FakeConnector()
    request = _httpx.Request("GET", "https://example.com")
    response = _httpx.Response(429, request=request, headers={"Retry-After": "5"})

    delay = BasePublicConnector._mark_rate_limited(connector, response)
    assert delay == 5.0
    assert resources.consecutive_rate_limits == 1
    assert resources.rate_limited_until > 0.0
    # A generic failure counter must remain untouched by a rate-limit event.
    assert resources.consecutive_failures == 0


def test_repeated_rate_limits_escalate_cooldown():
    import asyncio as _asyncio
    import logging as _logging
    import httpx as _httpx
    from trader_dost_arun.data.base import SharedHttpResources, BasePublicConnector

    resources = SharedHttpResources(client=None, semaphore=_asyncio.Semaphore(1))

    class _FakeConnector:
        venue = "binance"
        symbol = "group-1"
        config: dict = {}

        def __init__(self):
            self._http_resources = resources
            self.logger = _logging.getLogger("test")

    connector = _FakeConnector()
    request = _httpx.Request("GET", "https://example.com")
    # No Retry-After this time - falls back to escalating base cooldown.
    response = _httpx.Response(429, request=request)

    first_delay = BasePublicConnector._mark_rate_limited(connector, response)
    second_delay = BasePublicConnector._mark_rate_limited(connector, response)
    assert second_delay > first_delay  # escalates with consecutive_rate_limits
    assert resources.consecutive_rate_limits == 2


# ---------------------------------------------------------------------------
# Fix 7 (found during continued audit): the same strategy must not re-fire
# a signal for a symbol/venue it already holds an open position on, and
# duplicate alerts within a cooldown window must not be sent (or counted
# as delivery failures).
# ---------------------------------------------------------------------------

def test_signal_alert_deduped_within_cooldown_does_not_count_as_failure(tmp_path: Path):
    import asyncio as _asyncio
    from trader_dost_arun.ops.alerts import TelegramAlerter

    async def _run():
        alerter = TelegramAlerter(token="fake-token", chat_id="123", counter_db=tmp_path / "counter.sqlite3")

        async def _always_sent(*_a, **_kw):
            return True

        alerter.send = _always_sent
        signal = _make_position("alpha").signal
        first = await alerter.signal_alert(signal)
        second = await alerter.signal_alert(signal)  # same key, within cooldown
        return alerter, first, second

    alerter, first, second = _asyncio.run(_run())
    assert first == "sent"
    assert second == "duplicate"
    # A deduped alert must not be counted as a delivery failure.
    assert alerter.total_signal_alerts_failed == 0
    assert alerter.total_signal_alerts_sent == 1


def test_engine_suppresses_duplicate_signal_for_open_position(tmp_path: Path):
    """The engine-level gate: a strategy with an existing open position on a
    symbol/venue must not accept a new candidate signal for the same
    strategy+symbol+venue."""
    from trader_dost_arun.signals.engine import SignalEngine

    config = {
        "risk": {"daily_loss_limit_r": 4, "kill_switch_after_consecutive_losses": 4},
        "adaptive": {
            "kelly_cap": 0.03, "kelly_fraction": 0.5, "hmm_regimes": 3, "hmm_min_samples": 5,
            "hmm_refit_seconds": 9999, "hmm_transition_confirmation_ticks": 1,
            "meta_label_threshold": 0.0, "max_gross_exposure": 1.0, "max_same_direction_exposure": 1.0,
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
        "strategies": {},
        "vetoes": {
            "exchange_instability": {"max_feed_lag_seconds": 999, "max_mark_index_gap_bps": 999},
            "volatility_anomaly": {"rv_5m_max": 999},
            "correlation_spike": {"dispersion_limit": 999},
            "cross_venue_dispersion": {"price_dispersion_limit": 999, "premium_dispersion_limit": 999},
            "funding_proximity": {"pre_minutes": 0, "post_minutes": 0},
            "liquidation_tape": {"liquidation_notional_limit": 999_999_999},
            "freshness_quorum": {"min_sources": 0},
        },
        "execution": {"slippage_mode": "optimistic"},
        "positions": {"db_path": str(tmp_path / "positions.sqlite3")},
        "checkpoint": {"path": str(tmp_path / "checkpoint.json")},
    }
    engine = SignalEngine(config, news_guard=None)
    position = _make_position("alpha")
    position.signal.symbol = "BTCUSDT"
    position.signal.venue = "binance"
    position.closed_at = None
    engine.exposure.add_position(position)

    assert engine._has_open_position("alpha", "BTCUSDT", "binance") is True
    assert engine._has_open_position("alpha", "ETHUSDT", "binance") is False
    assert engine._has_open_position("beta", "BTCUSDT", "binance") is False
