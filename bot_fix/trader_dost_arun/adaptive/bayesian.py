from __future__ import annotations

from collections import defaultdict
from math import sqrt
from typing import DefaultDict

try:
    from scipy.stats import beta as beta_dist
except Exception:  # noqa: BLE001
    beta_dist = None


class BayesianConfidenceModel:
    """Beta-Binomial confidence model with hierarchical shrinkage."""

    def __init__(self, priors: dict[str, float], prior_strength: float = 10.0) -> None:
        self.prior_strength = prior_strength
        self.alpha_beta: DefaultDict[tuple[str, str], list[float]] = defaultdict(lambda: [1.0, 1.0])
        self.samples: DefaultDict[tuple[str, str], int] = defaultdict(int)
        for strategy, prior_pct in priors.items():
            self.alpha_beta[(strategy, "global")] = self._prior_to_alpha_beta(prior_pct)

    def _prior_to_alpha_beta(self, prior_pct: float) -> list[float]:
        p = min(max(prior_pct / 100.0, 1e-3), 1 - 1e-3)
        alpha = p * self.prior_strength
        beta = (1.0 - p) * self.prior_strength
        return [alpha, beta]

    def update(self, strategy: str, regime: str, outcome: int) -> None:
        key = (strategy, regime)
        if key not in self.alpha_beta:
            self.alpha_beta[key] = list(self.alpha_beta.get((strategy, "global"), [self.prior_strength / 2, self.prior_strength / 2]))
        alpha, beta = self.alpha_beta[key]
        if outcome > 0:
            alpha += 1
        else:
            beta += 1
        self.alpha_beta[key] = [alpha, beta]
        self.samples[key] += 1
        global_key = (strategy, "global")
        g_alpha, g_beta = self.alpha_beta.get(global_key, [self.prior_strength / 2, self.prior_strength / 2])
        if outcome > 0:
            g_alpha += 1
        else:
            g_beta += 1
        self.alpha_beta[global_key] = [g_alpha, g_beta]
        self.samples[global_key] += 1

    def _posterior(self, strategy: str, regime: str) -> tuple[float, float]:
        local = self.alpha_beta.get((strategy, regime))
        global_ab = self.alpha_beta.get((strategy, "global"), [self.prior_strength / 2, self.prior_strength / 2])
        if local is None:
            return float(global_ab[0]), float(global_ab[1])
        n = self.samples.get((strategy, regime), 0)
        if regime != "global" and n < 30:
            shrink = n / 30.0
            alpha = local[0] * shrink + global_ab[0] * (1 - shrink)
            beta = local[1] * shrink + global_ab[1] * (1 - shrink)
            return float(alpha), float(beta)
        return float(local[0]), float(local[1])

    def credible_interval(self, strategy: str, regime: str, level: float = 0.95) -> tuple[float, float]:
        alpha, beta = self._posterior(strategy, regime)
        tail = (1.0 - level) / 2
        if beta_dist is not None:
            return float(beta_dist.ppf(tail, alpha, beta) * 100), float(beta_dist.ppf(1 - tail, alpha, beta) * 100)
        mean = alpha / (alpha + beta)
        variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1))
        std = sqrt(max(variance, 0.0))
        z = 1.96
        return max(0.0, (mean - z * std) * 100), min(100.0, (mean + z * std) * 100)

    def confidence(self, strategy: str, regime: str) -> tuple[float, float]:
        alpha, beta = self._posterior(strategy, regime)
        mean = alpha / (alpha + beta)
        lower, _ = self.credible_interval(strategy, regime)
        return mean * 100, lower
