from __future__ import annotations

import math
from collections import Counter
from math import sqrt
from statistics import mean, pstdev

import numpy as np

from trader_dost_arun.core.models import Direction, FeatureSet, MarketSnapshot, MarketStateView


def _is_finite(value: float | int | None) -> bool:
    return value is not None and math.isfinite(float(value))


def _finite_values(values: list[float], *, positive_only: bool = False) -> list[float]:
    cleaned = [float(value) for value in values if _is_finite(value)]
    if positive_only:
        cleaned = [value for value in cleaned if value > 0]
    return cleaned


def _safe_float(value: float | int | None, default: float = 0.0, *, positive_only: bool = False) -> float:
    if not _is_finite(value):
        return default
    numeric = float(value)
    if positive_only and numeric <= 0:
        return default
    return numeric


def _zscore(values: list[float], current: float, window: int | None = None) -> float:
    current_value = _safe_float(current)
    series = _finite_values(values)
    if window is not None and len(series) > window:
        series = series[-window:]
    if len(series) < 3:
        return 0.0
    # numpy std is ~10-50x faster than statistics.pstdev for >=1000 samples and
    # avoids the exact rational arithmetic that made _zscore the dominant
    # cost on large history windows.
    arr = np.asarray(series, dtype=float)
    sigma = float(np.std(arr))
    if sigma == 0.0:
        return 0.0
    return float((current_value - float(arr.mean())) / sigma)


def order_book_imbalance(snapshot: MarketSnapshot, levels: int = 10) -> float:
    bid = sum(level.size for level in snapshot.bid_levels[:levels] if _is_finite(level.size))
    ask = sum(level.size for level in snapshot.ask_levels[:levels] if _is_finite(level.size))
    denom = bid + ask
    return (bid - ask) / denom if denom else 0.0


def trade_delta(trades: list, window: int = 200) -> float:
    sample = trades[-window:]
    return sum(_safe_float(t.size) if t.side == Direction.LONG else -_safe_float(t.size) for t in sample)


def vwap(prices: list[float], volumes: list[float]) -> float:
    pairs = [(_safe_float(price, positive_only=True), _safe_float(volume, positive_only=True)) for price, volume in zip(prices, volumes, strict=False)]
    pairs = [(price, volume) for price, volume in pairs if price > 0 and volume > 0]
    if not pairs:
        return 0.0
    total = sum(price * volume for price, volume in pairs)
    return total / max(sum(volume for _, volume in pairs), 1e-9)


def rolling_vwap(view: MarketStateView, window: int = 100) -> float:
    prices = [t.price for t in view.trades[-window:]]
    volumes = [t.size for t in view.trades[-window:]]
    return vwap(prices, volumes)


def volume_profile(view: MarketStateView, bins: int = 20) -> dict[str, float]:
    if not view.trades:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "hvn": 0.0, "lvn": 0.0}
    pairs = [(_safe_float(t.price, positive_only=True), _safe_float(t.size, positive_only=True)) for t in view.trades]
    pairs = [(price, volume) for price, volume in pairs if price > 0 and volume > 0]
    if not pairs:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "hvn": 0.0, "lvn": 0.0}
    prices = np.array([price for price, _ in pairs], dtype=float)
    volumes = np.array([volume for _, volume in pairs], dtype=float)
    hist, edges = np.histogram(prices, bins=bins, weights=volumes)
    if not np.isfinite(hist).all() or hist.sum() <= 0:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "hvn": 0.0, "lvn": 0.0}
    poc_index = int(hist.argmax())
    poc = float((edges[poc_index] + edges[poc_index + 1]) / 2)
    cumulative = hist.cumsum() / max(hist.sum(), 1e-9)
    val_idx = int(np.searchsorted(cumulative, 0.15))
    vah_idx = int(np.searchsorted(cumulative, 0.85))
    hvn = float((edges[int(hist.argmax())] + edges[int(hist.argmax()) + 1]) / 2)
    lvn = float((edges[int(hist.argmin())] + edges[int(hist.argmin()) + 1]) / 2)
    return {
        "poc": poc,
        "vah": float(edges[min(vah_idx + 1, len(edges) - 1)]),
        "val": float(edges[val_idx]),
        "hvn": hvn,
        "lvn": lvn,
    }


def atr(view: MarketStateView, window: int = 14) -> float:
    # Operate only on the tail needed to fill the ATR window. Iterating the
    # full closes/highs/lows series scaled with history length and was the
    # dominant cost (~7ms per call on 3000 samples). The result is unchanged:
    # ATR only reads the last (window+1) triplets regardless of total history.
    max_needed = min(window + 2, len(view.closes), len(view.highs), len(view.lows))
    if max_needed < 2:
        return 0.0
    closes = _finite_values(list(view.closes)[-max_needed:], positive_only=True)
    highs = _finite_values(list(view.highs)[-max_needed:], positive_only=True)
    lows = _finite_values(list(view.lows)[-max_needed:], positive_only=True)
    if len(closes) < 2:
        return 0.0
    trs: list[float] = []
    n = min(len(closes), len(highs), len(lows))
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    sample = _finite_values(trs[-window:] if len(trs) >= window else trs)
    return mean(sample) if sample else 0.0


def realized_vol(view: MarketStateView, window: int = 60) -> float:
    closes = _finite_values(view.closes[-window:], positive_only=True)
    if len(closes) < 3:
        return 0.0
    returns = np.diff(np.log(np.array(closes, dtype=float)))
    finite_returns = returns[np.isfinite(returns)]
    if len(finite_returns) < 2:
        return 0.0
    return float(np.std(finite_returns) * sqrt(len(finite_returns)))


def sanitize_feature_values(values: dict[str, float | int | bool | str]) -> dict[str, float | int | bool | str]:
    cleaned: dict[str, float | int | bool | str] = {}
    for key, value in values.items():
        if isinstance(value, bool):
            cleaned[key] = value
            continue
        if isinstance(value, (int, float)):
            cleaned[key] = float(value) if math.isfinite(float(value)) else 0.0
            continue
        cleaned[key] = value
    return cleaned


def compute_features(view: MarketStateView, peer_views: dict[str, MarketStateView]) -> FeatureSet:
    latest = view.latest
    if latest is None:
        raise ValueError("Cannot compute features without at least one market snapshot")
    missing: set[str] = set()
    ofi = order_book_imbalance(latest, 10)
    # Use the store-maintained running aggregates when available so the hot path
    # never rescans the full snapshot/trade history (O(history) -> O(1)).
    delta = view.trade_delta200 if view.trade_delta200 is not None else trade_delta(view.trades)
    if view.vwap_price_volume_120 is not None and view.vwap_volume_120 and view.vwap_volume_120 > 0:
        rvwap = view.vwap_price_volume_120 / view.vwap_volume_120
    else:
        rvwap = rolling_vwap(view, 120)
    if view.vwap_price_volume_total is not None and view.vwap_volume_total and view.vwap_volume_total > 0:
        session_vwap = view.vwap_price_volume_total / view.vwap_volume_total
    else:
        session_vwap = rolling_vwap(view, len(view.trades)) if view.trades else 0.0
    profile = volume_profile(view)
    if not view.open_interests:
        # REST enrichment (e.g. /fapi/v1/openInterest) has never successfully
        # returned data for this symbol - current_oi/delta_oi below are
        # placeholders, not a real "no change" reading of zero.
        missing.add("open_interest")
        missing.add("delta_oi")
    current_oi = _safe_float(view.open_interests[-1] if view.open_interests else 0.0)
    previous_oi = _safe_float(view.open_interests[-2] if len(view.open_interests) > 1 else current_oi)
    delta_oi = current_oi - previous_oi
    if not view.funding_rates:
        missing.add("funding_rate")
        missing.add("funding_zscore")
    funding = _safe_float(view.funding_rates[-1] if view.funding_rates else 0.0)
    funding_z = _zscore(view.funding_rates[:-1], funding) if len(view.funding_rates) > 3 else 0.0
    latest_mark = _safe_float(latest.mark_price, positive_only=True)
    latest_index = _safe_float(latest.index_price, positive_only=True)
    if latest_mark <= 0.0:
        missing.add("mark_price")
    if latest_index <= 0.0:
        missing.add("index_price")
    if not view.premiums:
        missing.add("premium")
        missing.add("premium_zscore")
    premium = _safe_float(view.premiums[-1] if view.premiums else (latest_mark - latest_index))
    premium_z = _zscore(view.premiums[:-1], premium) if len(view.premiums) > 3 else 0.0
    liquidation_notional = sum(_safe_float(item.notional, default=0.0) for item in view.liquidations[-50:])
    liquidation_series = [_safe_float(item.notional, default=0.0) for item in view.liquidations[:-1]]
    latest_liq = _safe_float(view.liquidations[-1].notional, default=0.0) if view.liquidations else 0.0
    liq_z = _zscore(liquidation_series[-500:], latest_liq) if len(view.liquidations) > 3 else 0.0
    peer_mid_prices = {venue: _safe_float(peer.latest.mid_price, default=0.0, positive_only=True) for venue, peer in peer_views.items() if peer.latest}
    peer_price_values = [price for price in peer_mid_prices.values() if price > 0]
    price_dispersion = float(np.std(peer_price_values)) if len(peer_price_values) > 1 else 0.0
    premium_values = [float(premium_value) for peer in peer_views.values() for premium_value in ([peer.premiums[-1]] if peer.premiums and _is_finite(peer.premiums[-1]) else [])]
    premium_dispersion = float(np.std(premium_values)) if len(premium_values) > 1 else 0.0
    side_counter = Counter(t.side for t in view.trades[-100:])
    taker_ratio = side_counter[Direction.LONG] / max(side_counter[Direction.SHORT], 1)
    same_side_depth = sum(level.size for level in latest.bid_levels[:10] if _is_finite(level.size)) if ofi >= 0 else sum(level.size for level in latest.ask_levels[:10] if _is_finite(level.size))
    adverse_depth = sum(level.size for level in latest.ask_levels[:10] if _is_finite(level.size)) if ofi >= 0 else sum(level.size for level in latest.bid_levels[:10] if _is_finite(level.size))
    spread = _safe_float(latest.spread, default=0.0)
    if spread == 0.0 and latest.ask_levels and latest.bid_levels:
        spread = _safe_float(latest.ask_levels[0].price) - _safe_float(latest.bid_levels[0].price)
    option_iv_series = view.option_atm_iv_series if view.option_atm_iv_series is not None else [float(snap.option_atm_iv) for snap in view.snapshots if _is_finite(snap.option_atm_iv)]
    option_skew_series = view.option_put_call_skew_series if view.option_put_call_skew_series is not None else [float(snap.option_put_call_skew) for snap in view.snapshots if _is_finite(snap.option_put_call_skew)]
    cvd_value = view.cvd_total if view.cvd_total is not None else trade_delta(view.trades, len(view.trades))
    ofi_history = view.ofi_series if view.ofi_series is not None else [order_book_imbalance(s, 10) for s in view.snapshots[:-1] if s.bid_levels and s.ask_levels]
    values = {
        "order_book_imbalance": ofi,
        "ofi_zscore": _zscore(ofi_history[-250:], ofi),
        "trade_delta": delta,
        "cvd": cvd_value,
        "rolling_vwap": rvwap,
        "session_vwap": session_vwap,
        "poc": profile["poc"],
        "vah": profile["vah"],
        "val": profile["val"],
        "hvn": profile["hvn"],
        "lvn": profile["lvn"],
        "open_interest": current_oi,
        "delta_oi": delta_oi,
        "funding_rate": funding,
        "funding_zscore": funding_z,
        "premium": premium,
        "premium_zscore": premium_z,
        "liquidation_notional": liquidation_notional,
        "liquidation_zscore": liq_z,
        "price_dispersion": price_dispersion,
        "premium_dispersion": premium_dispersion,
        "taker_ratio": taker_ratio,
        "same_side_depth": same_side_depth,
        "adverse_depth": adverse_depth,
        "spread": spread,
        "spread_percentile": spread,
        "realized_vol_1m": realized_vol(view, 60),
        "realized_vol_5m": realized_vol(view, 300),
        "atr": atr(view, 14),
        "microprice": _safe_float(latest.microprice, default=0.0, positive_only=True),
        "mid_price": _safe_float(latest.mid_price, default=0.0, positive_only=True),
        "mark_price": latest_mark,
        "index_price": latest_index,
        "option_atm_iv": _safe_float(latest.option_atm_iv, default=0.0),
        "option_put_call_skew": _safe_float(latest.option_put_call_skew, default=0.0),
        "option_iv_zscore": _zscore(option_iv_series[:-1], _safe_float(latest.option_atm_iv, default=0.0)) if len(option_iv_series) > 3 else 0.0,
        "option_skew_zscore": _zscore(option_skew_series[:-1], _safe_float(latest.option_put_call_skew, default=0.0)) if len(option_skew_series) > 3 else 0.0,
    }
    return FeatureSet(venue=latest.venue, symbol=latest.symbol, timestamp=latest.arrival_time, values=sanitize_feature_values(values), missing=frozenset(missing))
