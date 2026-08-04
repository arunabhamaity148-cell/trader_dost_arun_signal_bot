from __future__ import annotations

from collections import defaultdict
from statistics import mean

from trader_dost_arun.core.models import Direction, Trade


def footprint_bins(trades: list[Trade], price_step: float = 1.0) -> dict[float, dict[str, float]]:
    bins: dict[float, dict[str, float]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
    for trade in trades:
        level = round(trade.price / price_step) * price_step
        key = "buy" if trade.side == Direction.LONG else "sell"
        bins[level][key] += trade.size
    return dict(sorted(bins.items()))


def delta_divergence(prices: list[float], deltas: list[float]) -> str:
    if len(prices) < 2 or len(deltas) < 2:
        return "none"
    price_up = prices[-1] > prices[0]
    delta_up = deltas[-1] > deltas[0]
    if price_up and not delta_up:
        return "bearish"
    if not price_up and delta_up:
        return "bullish"
    return "none"


def stacked_imbalances(footprint: dict[float, dict[str, float]], threshold: float = 2.0) -> int:
    streak = 0
    best = 0
    direction = None
    for level, row in footprint.items():
        buy = row["buy"]
        sell = row["sell"]
        side = "buy" if buy > sell * threshold else "sell" if sell > buy * threshold else None
        if side and side == direction:
            streak += 1
        elif side:
            direction = side
            streak = 1
        else:
            direction = None
            streak = 0
        best = max(best, streak)
    return best


def poc_migration(footprints: list[dict[float, dict[str, float]]]) -> float:
    pocs: list[float] = []
    for fp in footprints:
        if not fp:
            continue
        poc = max(fp.items(), key=lambda item: item[1]["buy"] + item[1]["sell"])[0]
        pocs.append(float(poc))
    return pocs[-1] - pocs[0] if len(pocs) >= 2 else 0.0


def value_area(footprint: dict[float, dict[str, float]], coverage: float = 0.7) -> tuple[float, float]:
    if not footprint:
        return 0.0, 0.0
    totals = sorted(((level, row["buy"] + row["sell"]) for level, row in footprint.items()), key=lambda item: item[0])
    total_volume = sum(v for _, v in totals)
    cumulative = 0.0
    selected: list[float] = []
    for level, volume in sorted(totals, key=lambda item: item[1], reverse=True):
        cumulative += volume
        selected.append(level)
        if cumulative / max(total_volume, 1e-9) >= coverage:
            break
    return min(selected), max(selected)


def composite_volume_profile(footprints: list[dict[float, dict[str, float]]]) -> dict[float, float]:
    profile: dict[float, float] = defaultdict(float)
    for fp in footprints:
        for level, row in fp.items():
            profile[level] += row["buy"] + row["sell"]
    return dict(profile)
