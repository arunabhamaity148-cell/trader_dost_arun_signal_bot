from __future__ import annotations

from collections import defaultdict


def estimate_liquidation_zones(prices: list[float], open_interest: list[float], leverage: float = 5.0) -> dict[float, float]:
    zones: dict[float, float] = defaultdict(float)
    if len(prices) < 2 or len(open_interest) < 2:
        return {}
    for idx in range(1, min(len(prices), len(open_interest))):
        oi_added = open_interest[idx] - open_interest[idx - 1]
        if oi_added <= 0:
            continue
        move = prices[idx] / max(leverage, 1.0)
        zones[round(prices[idx] - move, 2)] += oi_added
        zones[round(prices[idx] + move, 2)] += oi_added
    return dict(sorted(zones.items()))


def liquidation_magnets(prices: list[float], open_interest: list[float]) -> list[float]:
    zones = estimate_liquidation_zones(prices, open_interest)
    return [level for level, score in sorted(zones.items(), key=lambda item: item[1], reverse=True)[:5]]


def liquidation_heatmap(prices: list[float], open_interest: list[float]) -> list[dict[str, float]]:
    zones = estimate_liquidation_zones(prices, open_interest)
    return [{"price": float(level), "intensity": float(score)} for level, score in zones.items()]
