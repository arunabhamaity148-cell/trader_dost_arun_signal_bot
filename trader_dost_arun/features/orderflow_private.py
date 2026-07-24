from __future__ import annotations

from collections import deque
from statistics import mean

from trader_dost_arun.core.models import Direction, OrderBookLevel, Trade


def trade_tape_imbalance(trades: list[Trade]) -> float:
    buy = sum(t.size * t.price for t in trades if t.side == Direction.LONG)
    sell = sum(t.size * t.price for t in trades if t.side == Direction.SHORT)
    denom = buy + sell
    return (buy - sell) / denom if denom else 0.0


def aggressor_persistence(trades: list[Trade]) -> int:
    streak = 0
    best = 0
    last = None
    for trade in trades:
        side = trade.side
        if side == last:
            streak += 1
        else:
            streak = 1
            last = side
        best = max(best, streak)
    return best


def spoofing_detection(order_book_events: list[tuple[float, list[OrderBookLevel], list[OrderBookLevel]]]) -> bool:
    recent = deque(maxlen=3)
    for timestamp, bids, asks in order_book_events:
        recent.append((timestamp, sum(level.size for level in bids[:3]), sum(level.size for level in asks[:3])))
        if len(recent) == 3:
            _, b0, a0 = recent[0]
            t2, b2, a2 = recent[-1]
            if t2 - recent[0][0] <= 2 and (abs(b0 - b2) > max(b0, 1.0) * 0.5 or abs(a0 - a2) > max(a0, 1.0) * 0.5):
                return True
    return False


def quote_stuffing_detection(order_book_events: list[tuple[float, int]]) -> bool:
    if len(order_book_events) < 5:
        return False
    window = order_book_events[-5:]
    changes = sum(event[1] for event in window)
    duration = window[-1][0] - window[0][0]
    return duration <= 2 and changes >= 50


def volume_clock(trades: list[Trade], threshold: float) -> int:
    cumulative = 0.0
    buckets = 0
    for trade in trades:
        cumulative += trade.size
        if cumulative >= threshold:
            buckets += 1
            cumulative = 0.0
    return buckets


def kyles_lambda(prices: list[float], signed_volume: list[float]) -> float:
    if len(prices) < 2 or len(prices) != len(signed_volume):
        return 0.0
    returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    vols = signed_volume[1:]
    denom = sum(v * v for v in vols)
    return sum(r * v for r, v in zip(returns, vols)) / denom if denom else 0.0
