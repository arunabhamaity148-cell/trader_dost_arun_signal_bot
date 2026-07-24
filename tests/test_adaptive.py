from trader_dost_arun.adaptive.bayesian import BayesianConfidenceModel
from trader_dost_arun.adaptive.kelly import BoundedKellySizer
from trader_dost_arun.core.models import StrategyPerformance


def test_kelly_sizer_is_bounded():
    perf = StrategyPerformance(wins=8, losses=2, total_r=10)
    size = BoundedKellySizer(max_fraction=0.02, fraction=0.5).size(perf)
    assert 0 <= size <= 0.02


def test_bayesian_confidence_updates():
    model = BayesianConfidenceModel({"x": 80})
    before, _ = model.confidence("x", "trending")
    model.update("x", "trending", 1)
    after, _ = model.confidence("x", "trending")
    assert after >= before
