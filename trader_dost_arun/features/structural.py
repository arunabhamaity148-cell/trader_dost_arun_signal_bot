from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean

from trader_dost_arun.core.models import Direction, MarketStateView, StructuralState


@dataclass(slots=True)
class SwingPoint:
    index: int
    price: float
    side: str


@dataclass(slots=True)
class OrderBlock:
    side: str
    low: float
    high: float
    mitigated: bool = False


def detect_swings(prices: list[float], lookback: int = 3) -> list[tuple[int, float, str]]:
    swings: list[tuple[int, float, str]] = []
    if len(prices) < lookback * 2 + 1:
        return swings
    for idx in range(lookback, len(prices) - lookback):
        left = prices[idx - lookback : idx]
        right = prices[idx + 1 : idx + lookback + 1]
        center = prices[idx]
        if center > max(left) and center >= max(right):
            swings.append((idx, center, "high"))
        elif center < min(left) and center <= min(right):
            swings.append((idx, center, "low"))
    return swings


def detect_bos_choch(prices: list[float], closes: list[float] | None = None, lookback: int = 3) -> tuple[bool, bool, Direction]:
    closes = closes or prices
    swings = detect_swings(prices, lookback=lookback)
    if len(closes) < 2:
        return False, False, Direction.FLAT
    if len(swings) < 2:
        recent_high = max(closes[-5:-1], default=closes[-1])
        recent_low = min(closes[-5:-1], default=closes[-1])
        rising = len(closes) >= 4 and max(closes[-4:]) > max(closes[:-4] or closes[-4:])
        falling = len(closes) >= 4 and min(closes[-4:]) < min(closes[:-4] or closes[-4:])
        trend = Direction.LONG if closes[-1] >= closes[0] else Direction.SHORT if closes[-1] < closes[0] else Direction.FLAT
        bos = closes[-1] > recent_high or closes[-1] < recent_low or rising or falling
        return bos, False, trend
    last_close = closes[-1]
    swing_highs = [p for _, p, side in swings if side == "high"]
    swing_lows = [p for _, p, side in swings if side == "low"]
    prev_high = swing_highs[-1] if swing_highs else max(prices[:-1], default=prices[-1])
    prev_low = swing_lows[-1] if swing_lows else min(prices[:-1], default=prices[-1])
    recent_high = max(closes[-5:-1], default=last_close)
    recent_low = min(closes[-5:-1], default=last_close)
    rolling_break = max(closes[-4:], default=last_close) > max(closes[-8:-4] or closes[:-4] or [last_close]) or min(closes[-4:], default=last_close) < min(closes[-8:-4] or closes[:-4] or [last_close])
    bos = (
        last_close > prev_high
        or last_close < prev_low
        or last_close > recent_high
        or last_close < recent_low
        or rolling_break
        or (len(swing_highs) >= 2 and swing_highs[-1] > swing_highs[-2])
        or (len(swing_lows) >= 2 and swing_lows[-1] < swing_lows[-2])
    )
    choch = False
    trend = Direction.FLAT
    if last_close > prev_high:
        trend = Direction.LONG
        if len(swing_lows) >= 2 and swing_lows[-1] < swing_lows[-2]:
            choch = True
    elif last_close < prev_low:
        trend = Direction.SHORT
        if len(swing_highs) >= 2 and swing_highs[-1] > swing_highs[-2]:
            choch = True
    elif len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]:
            trend = Direction.LONG
        elif swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]:
            trend = Direction.SHORT
        elif (swing_highs[-1] > swing_highs[-2] and swing_lows[-1] < swing_lows[-2]) or (swing_highs[-1] < swing_highs[-2] and swing_lows[-1] > swing_lows[-2]):
            choch = True
    return bos, choch, trend


def detect_fvg(highs: list[float], lows: list[float]) -> tuple[bool, bool]:
    if len(highs) < 3 or len(lows) < 3:
        return False, False
    bullish = lows[-1] > highs[-3]
    bearish = highs[-1] < lows[-3]
    return bullish, bearish


def _last_matching_candle(opens: list[float], closes: list[float], start: int, end: int, *, bearish: bool) -> int | None:
    indices = range(end - 1, start - 1, -1)
    for idx in indices:
        if bearish and closes[idx] < opens[idx]:
            return idx
        if not bearish and closes[idx] > opens[idx]:
            return idx
    return None


def detect_order_blocks(opens: list[float], closes: list[float], highs: list[float], lows: list[float]) -> tuple[OrderBlock | None, OrderBlock | None]:
    if len(closes) < 4:
        return None, None
    bullish: OrderBlock | None = None
    bearish: OrderBlock | None = None
    for idx in range(1, len(closes)):
        window_start = max(0, idx - 3)
        prior_highs = highs[window_start:idx]
        prior_lows = lows[window_start:idx]
        if prior_highs and closes[idx] > max(prior_highs):
            source_idx = _last_matching_candle(opens, closes, window_start, idx, bearish=True)
            if source_idx is not None:
                bullish = OrderBlock("bullish", lows[source_idx], highs[source_idx], mitigated=closes[-1] < lows[source_idx])
        if prior_lows and closes[idx] < min(prior_lows):
            source_idx = _last_matching_candle(opens, closes, window_start, idx, bearish=False)
            if source_idx is not None:
                bearish = OrderBlock("bearish", lows[source_idx], highs[source_idx], mitigated=closes[-1] > highs[source_idx])
    return bullish, bearish


def detect_liquidity_sweep(prices: list[float]) -> tuple[bool, bool]:
    if len(prices) < 8:
        return False, False
    prior_high = max(prices[-8:-2])
    prior_low = min(prices[-8:-2])
    bullish = prices[-2] < prior_low and prices[-1] > prior_low
    bearish = prices[-2] > prior_high and prices[-1] < prior_high
    return bullish, bearish


def premium_discount_zone(prices: list[float]) -> str:
    if len(prices) < 2:
        return "equilibrium"
    lo, hi = min(prices), max(prices)
    midpoint = (lo + hi) / 2
    return "discount" if prices[-1] < midpoint else "premium" if prices[-1] > midpoint else "equilibrium"


def multi_timeframe_alignment(price_series_by_tf: dict[str, list[float]]) -> Direction:
    votes: list[Direction] = []
    for prices in price_series_by_tf.values():
        if len(prices) < 4:
            continue
        short = mean(prices[-3:])
        long = mean(prices[-8:]) if len(prices) >= 8 else mean(prices)
        if short > long:
            votes.append(Direction.LONG)
        elif short < long:
            votes.append(Direction.SHORT)
    if votes.count(Direction.LONG) >= max(2, len(price_series_by_tf) // 2):
        return Direction.LONG
    if votes.count(Direction.SHORT) >= max(2, len(price_series_by_tf) // 2):
        return Direction.SHORT
    return Direction.FLAT


def build_structural_state(view: MarketStateView, delta_oi: float, timeframes: dict[str, list[float]] | None = None) -> StructuralState:
    bos, choch, swing_trend = detect_bos_choch(view.highs or view.closes, closes=view.closes)
    bullish_fvg, bearish_fvg = detect_fvg(view.highs, view.lows)
    opens = [view.closes[i - 1] if i > 0 else view.closes[0] for i in range(len(view.closes))] if view.closes else []
    bullish_ob, bearish_ob = detect_order_blocks(opens, view.closes, view.highs, view.lows)
    bullish_sweep, bearish_sweep = detect_liquidity_sweep(view.closes)
    trend = multi_timeframe_alignment(timeframes or {"1m": view.closes[-20:], "5m": view.closes[-60:], "15m": view.closes[-120:]})
    final_trend = trend if trend != Direction.FLAT else swing_trend
    details = {
        "swing_trend": swing_trend.value,
        "premium_discount": premium_discount_zone(view.closes[-100:] if view.closes else []),
        "inducement_level": max(view.highs[-5:], default=0.0) if final_trend == Direction.LONG else min(view.lows[-5:], default=0.0),
        "breaker_block": bool((bullish_ob and bullish_ob.mitigated) or (bearish_ob and bearish_ob.mitigated)),
        "bullish_order_block": asdict(bullish_ob) if bullish_ob else None,
        "bearish_order_block": asdict(bearish_ob) if bearish_ob else None,
    }
    return StructuralState(
        bos=bos,
        choch=choch,
        bullish_fvg_open=bullish_fvg,
        bearish_fvg_open=bearish_fvg,
        bullish_order_block_active=bool(bullish_ob and not bullish_ob.mitigated),
        bearish_order_block_active=bool(bearish_ob and not bearish_ob.mitigated),
        bullish_sweep=bullish_sweep,
        bearish_sweep=bearish_sweep,
        trend_alignment=final_trend,
        oi_alignment=(delta_oi >= 0 and final_trend != Direction.SHORT) or (delta_oi <= 0 and final_trend != Direction.LONG),
        details=details,
    )
