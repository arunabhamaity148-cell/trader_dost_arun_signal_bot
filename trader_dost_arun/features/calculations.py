from __future__ import annotations

from collections import Counter
from math import sqrt
from statistics import mean, pstdev

import numpy as np

from trader_dost_arun.core.models import Direction, FeatureSet, MarketSnapshot, MarketStateView


def _zscore(values: list[float], current: float) -> float:
    if len(values) < 3:
        return 0.0
    sigma = pstdev(values)
    if sigma == 0:
        return 0.0
    return (current - mean(values)) / sigma


def order_book_imbalance(snapshot: MarketSnapshot, levels: int = 10) -> float:
    bid = sum(level.size for level in snapshot.bid_levels[:levels])
    ask = sum(level.size for level in snapshot.ask_levels[:levels])
    denom = bid + ask
    return (bid - ask) / denom if denom else 0.0


def trade_delta(trades: list, window: int = 200) -> float:
    sample = trades[-window:]
    return sum(t.size if t.side == Direction.LONG else -t.size for t in sample)


def vwap(prices: list[float], volumes: list[float]) -> float:
    if not prices or not volumes or len(prices) != len(volumes):
        return 0.0
    total = sum(p * v for p, v in zip(prices, volumes))
    return total / max(sum(volumes), 1e-9)


def rolling_vwap(view: MarketStateView, window: int = 100) -> float:
    prices = [t.price for t in view.trades[-window:]]
    volumes = [t.size for t in view.trades[-window:]]
    return vwap(prices, volumes)


def volume_profile(view: MarketStateView, bins: int = 20) -> dict[str, float]:
    if not view.trades:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "hvn": 0.0, "lvn": 0.0}
    prices = np.array([t.price for t in view.trades])
    volumes = np.array([t.size for t in view.trades])
    hist, edges = np.histogram(prices, bins=bins, weights=volumes)
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
    if len(view.closes) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, min(len(view.closes), len(view.highs), len(view.lows))):
        high = view.highs[i]
        low = view.lows[i]
        prev_close = view.closes[i - 1]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    sample = trs[-window:] if len(trs) >= window else trs
    return mean(sample) if sample else 0.0


def realized_vol(view: MarketStateView, window: int = 60) -> float:
    closes = view.closes[-window:]
    if len(closes) < 3:
        return 0.0
    returns = np.diff(np.log(np.array(closes)))
    return float(np.std(returns) * sqrt(len(returns)))


def compute_features(view: MarketStateView, peer_views: dict[str, MarketStateView]) -> FeatureSet:
    latest = view.latest
    if latest is None:
        raise ValueError("Cannot compute features without at least one market snapshot")
    ofi = order_book_imbalance(latest, 10)
    delta = trade_delta(view.trades)
    rvwap = rolling_vwap(view, 120)
    session_vwap = rolling_vwap(view, len(view.trades)) if view.trades else 0.0
    profile = volume_profile(view)
    current_oi = view.open_interests[-1] if view.open_interests else 0.0
    previous_oi = view.open_interests[-2] if len(view.open_interests) > 1 else current_oi
    delta_oi = current_oi - previous_oi
    funding = view.funding_rates[-1] if view.funding_rates else 0.0
    funding_z = _zscore(view.funding_rates[:-1], funding) if len(view.funding_rates) > 3 else 0.0
    premium = view.premiums[-1] if view.premiums else ((latest.mark_price or 0.0) - (latest.index_price or 0.0))
    premium_z = _zscore(view.premiums[:-1], premium) if len(view.premiums) > 3 else 0.0
    liquidation_notional = sum(item.notional for item in view.liquidations[-50:])
    liquidation_series = [item.notional for item in view.liquidations[:-1]]
    liq_z = _zscore(liquidation_series[-500:], view.liquidations[-1].notional) if len(view.liquidations) > 3 else 0.0
    peer_mid_prices = {venue: peer.latest.mid_price for venue, peer in peer_views.items() if peer.latest and peer.latest.mid_price}
    peer_price_values = [p for p in peer_mid_prices.values() if p]
    price_dispersion = float(np.std(peer_price_values)) if len(peer_price_values) > 1 else 0.0
    premium_values = [peer.premiums[-1] for peer in peer_views.values() if peer.premiums]
    premium_dispersion = float(np.std(premium_values)) if len(premium_values) > 1 else 0.0
    side_counter = Counter(t.side for t in view.trades[-100:])
    taker_ratio = side_counter[Direction.LONG] / max(side_counter[Direction.SHORT], 1)
    same_side_depth = sum(level.size for level in latest.bid_levels[:10]) if ofi >= 0 else sum(level.size for level in latest.ask_levels[:10])
    adverse_depth = sum(level.size for level in latest.ask_levels[:10]) if ofi >= 0 else sum(level.size for level in latest.bid_levels[:10])
    spread = latest.spread or ((latest.ask_levels[0].price - latest.bid_levels[0].price) if latest.ask_levels and latest.bid_levels else 0.0)
    option_iv_series = [snap.option_atm_iv for snap in view.snapshots if snap.option_atm_iv is not None]
    option_skew_series = [snap.option_put_call_skew for snap in view.snapshots if snap.option_put_call_skew is not None]
    values = {
        "order_book_imbalance": ofi,
        "ofi_zscore": _zscore([order_book_imbalance(s, 10) for s in view.snapshots[:-1] if s.bid_levels and s.ask_levels][-250:], ofi),
        "trade_delta": delta,
        "cvd": trade_delta(view.trades, len(view.trades)),
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
        "microprice": latest.microprice or 0.0,
        "mid_price": latest.mid_price or 0.0,
        "mark_price": latest.mark_price or 0.0,
        "index_price": latest.index_price or 0.0,
        "option_atm_iv": latest.option_atm_iv or 0.0,
        "option_put_call_skew": latest.option_put_call_skew or 0.0,
        "option_iv_zscore": _zscore(option_iv_series[:-1], latest.option_atm_iv or 0.0) if len(option_iv_series) > 3 else 0.0,
        "option_skew_zscore": _zscore(option_skew_series[:-1], latest.option_put_call_skew or 0.0) if len(option_skew_series) > 3 else 0.0,
    }
    return FeatureSet(venue=latest.venue, symbol=latest.symbol, timestamp=latest.event_time, values=values)
