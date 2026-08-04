from __future__ import annotations

from math import sqrt
from statistics import mean


def sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    avg = mean(returns)
    variance = sum((x - avg) ** 2 for x in returns) / (len(returns) - 1)
    std = variance ** 0.5
    return avg / std * sqrt(len(returns)) if std else 0.0


def sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    avg = mean(returns)
    downside = [min(0.0, x) for x in returns]
    variance = sum(x * x for x in downside) / max(len(downside), 1)
    std = variance ** 0.5
    return avg / std * sqrt(len(returns)) if std else 0.0


def max_drawdown(equity_curve: list[float]) -> float:
    peak = float("-inf")
    drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, (value - peak) / peak)
    return abs(drawdown)


def calmar(total_return: float, equity_curve: list[float]) -> float:
    mdd = max_drawdown(equity_curve)
    return total_return / mdd if mdd else 0.0


def profit_factor(returns: list[float]) -> float:
    gross_win = sum(x for x in returns if x > 0)
    gross_loss = abs(sum(x for x in returns if x < 0))
    return gross_win / gross_loss if gross_loss else gross_win


def expectancy(returns: list[float]) -> float:
    return mean(returns) if returns else 0.0


def regime_breakdown(rows: list[dict[str, float | str]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        key = f"{row.get('strategy_name','unknown')}::{row.get('regime_at_exit','unknown')}"
        grouped.setdefault(key, []).append(float(row.get("realized_r", 0.0)))
    return {
        key: {
            "count": float(len(values)),
            "win_rate": sum(1 for x in values if x > 0) / max(len(values), 1),
            "expectancy": expectancy(values),
        }
        for key, values in grouped.items()
    }
