from trader_dost_arun.features.structural import detect_bos_choch, detect_fvg, detect_liquidity_sweep


def test_detect_bos_and_trend():
    bos, _, trend = detect_bos_choch([1, 2, 1.5, 3, 2.2, 4, 3.1, 5, 4.2])
    assert bos is True
    assert trend.value in {"long", "flat"}


def test_detect_fvg_and_sweep():
    bullish_fvg, bearish_fvg = detect_fvg([10, 11, 12], [9, 10.5, 11.5])
    assert bullish_fvg or bearish_fvg
    bullish_sweep, bearish_sweep = detect_liquidity_sweep([10, 11, 12, 11, 10.5, 9.8, 9.2, 10.4])
    assert isinstance(bullish_sweep, bool)
    assert isinstance(bearish_sweep, bool)
