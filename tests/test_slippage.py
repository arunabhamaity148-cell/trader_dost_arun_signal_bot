from trader_dost_arun.core.models import Direction
from trader_dost_arun.execution.slippage import SlippageModel


def test_realistic_slippage_uses_expected_params():
    model = SlippageModel("realistic")
    assert model.slippage_bps(1.0, 1000.0) >= 2.0


def test_conservative_is_worse_than_aggressive():
    conservative = SlippageModel("conservative").slippage_bps(10.0, 100.0)
    aggressive = SlippageModel("aggressive").slippage_bps(10.0, 100.0)
    assert conservative > aggressive


def test_long_fill_is_above_entry():
    fill, _ = SlippageModel().expected_fill_price(100.0, Direction.LONG, 1.0, 1.0, 1000.0)
    assert fill > 100.0


def test_short_fill_is_below_entry():
    fill, _ = SlippageModel().expected_fill_price(100.0, Direction.SHORT, 1.0, 1.0, 1000.0)
    assert fill < 100.0


def test_depth_sensitive_slippage_increases_for_large_size():
    model = SlippageModel()
    small = model.slippage_bps(1.0, 1000.0)
    large = model.slippage_bps(100.0, 1000.0)
    assert large > small
