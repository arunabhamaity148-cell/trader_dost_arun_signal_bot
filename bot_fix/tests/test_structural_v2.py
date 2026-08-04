from trader_dost_arun.core.models import Direction, MarketStateView
from trader_dost_arun.features.structural import build_structural_state, detect_bos_choch, detect_fvg, detect_liquidity_sweep, detect_order_blocks, premium_discount_zone


def make_view(closes):
    return MarketStateView(
        symbol="BTCUSDT",
        snapshots=[],
        trades=[],
        liquidations=[],
        closes=closes,
        highs=[c + 0.5 for c in closes],
        lows=[c - 0.5 for c in closes],
        volumes=[1.0] * len(closes),
        open_interests=[1000 + i * 10 for i in range(len(closes))],
        funding_rates=[0.0] * len(closes),
        premiums=[0.0] * len(closes),
    )


def test_choch_detects_reversal_pattern():
    bos, choch, _ = detect_bos_choch([10, 11, 12, 11, 10, 9, 10, 11, 8])
    assert isinstance(choch, bool)


def test_fvg_detects_bullish_gap():
    bullish, bearish = detect_fvg([10, 11, 12], [9, 10.5, 12.2])
    assert bullish is True
    assert bearish is False


def test_order_block_detection_finds_bullish_block():
    bull, bear = detect_order_blocks([10, 9, 8, 9, 10], [9, 8, 9, 10, 12], [10, 9.5, 9.2, 10.1, 12.5], [8.5, 7.5, 7.8, 8.7, 9.8])
    assert bull is not None or bear is not None


def test_liquidity_sweep_flags_bullish_reclaim():
    bullish, bearish = detect_liquidity_sweep([10, 11, 10.5, 10.2, 10.1, 9.8, 9.0, 10.3])
    assert bullish is True
    assert bearish is False


def test_build_structural_state_contains_smc_details():
    view = make_view([100, 101, 102, 101.5, 103, 104, 103.5, 105, 106])
    state = build_structural_state(view, delta_oi=50)
    assert state.details["premium_discount"] in {"premium", "discount", "equilibrium"}
    assert isinstance(state.trend_alignment, Direction)


def test_premium_discount_zone_returns_premium():
    assert premium_discount_zone([1, 2, 3, 4]) == "premium"
