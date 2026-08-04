from __future__ import annotations

from trader_dost_arun.core.models import StrategyPerformance


class BoundedKellySizer:
    def __init__(self, max_fraction: float = 0.03, fraction: float = 0.5) -> None:
        self.max_fraction = max_fraction
        self.fraction = fraction

    def size(self, performance: StrategyPerformance) -> float:
        win_rate = performance.win_rate
        payoff = max(performance.payoff_ratio, 0.1)
        raw = win_rate - (1 - win_rate) / payoff
        bounded = max(0.0, raw * self.fraction)
        return min(bounded, self.max_fraction)
