from __future__ import annotations

from statistics import mean

from trader_dost_arun.core.models import Direction, FeatureSet, Signal, StructuralState
from trader_dost_arun.core.state import MarketStateStore


class DeterministicStrategyEngine:
    def __init__(self, config: dict):
        self.config = config
        self.priors = config["strategy_priors"]

    def evaluate_all(self, venue: str, symbol: str, features: FeatureSet, structural: StructuralState, state: MarketStateStore, peer_features: dict[str, FeatureSet], regime: str) -> list[Signal]:
        strategies = [
            self.liquidation_cascade_continuation,
            self.extreme_funding_crowding_reversion,
            self.order_flow_imbalance_continuation,
            self.aggressor_exhaustion_absorption_fade,
            self.fresh_oi_breakout_continuation,
            self.single_venue_premium_snapback,
            self.cross_venue_basis_dispersion_convergence,
            self.spot_index_lead_follow_through,
            self.funding_window_inventory_rebalance,
            self.deribit_iv_shock_repricing,
        ]
        results = []
        for strategy in strategies:
            signal = strategy(venue, symbol, features, structural, state, peer_features, regime)
            if signal:
                results.append(signal)
        return results

    def _build_signal(self, name: str, venue: str, symbol: str, direction: Direction, entry: float, stop: float, targets: list[float], confirmations: list[str], regime: str, metadata: dict | None = None) -> Signal:
        return Signal(name, symbol, venue, direction, entry, stop, targets, self.priors[name], 0.0, regime, confirmations, {}, metadata=metadata or {})

    def liquidation_cascade_continuation(self, venue, symbol, f, s, state, peers, regime):
        if f.get("liquidation_zscore") < 2.3 or abs(f.get("delta_oi")) <= 0 or f.get("adverse_depth") >= f.get("same_side_depth"):
            return None
        direction = Direction.SHORT if f.get("trade_delta") < 0 else Direction.LONG
        if s.trend_alignment not in {Direction.FLAT, direction}:
            return None
        entry = f.get("microprice") or f.get("mid_price")
        atr = max(f.get("atr"), entry * 0.0005)
        stop = entry + 0.7 * atr if direction == Direction.SHORT else entry - 0.7 * atr
        targets = [entry - 1.5 * abs(entry - stop), entry - 3 * abs(entry - stop)] if direction == Direction.SHORT else [entry + 1.5 * abs(entry - stop), entry + 3 * abs(entry - stop)]
        return self._build_signal("liquidation_cascade_continuation", venue, symbol, direction, entry, stop, targets, ["liquidation burst", "range break", "delta OI aligned", "adverse depth not replenishing"], regime)

    def extreme_funding_crowding_reversion(self, venue, symbol, f, s, state, peers, regime):
        if abs(f.get("funding_zscore")) < 2.5 or f.get("delta_oi") == 0 or abs(f.get("premium_zscore")) < 1.2:
            return None
        crowded_long = f.get("funding_zscore") > 0 and f.get("delta_oi") > 0
        crowded_short = f.get("funding_zscore") < 0 and f.get("delta_oi") > 0
        direction = Direction.SHORT if crowded_long else Direction.LONG if crowded_short else Direction.FLAT
        if direction == Direction.FLAT:
            return None
        entry = f.get("mid_price")
        atr = max(f.get("atr"), entry * 0.001)
        stop = entry + 0.5 * atr if direction == Direction.SHORT else entry - 0.5 * atr
        targets = [f.get("session_vwap"), f.get("rolling_vwap")]
        return self._build_signal("extreme_funding_crowding_reversion", venue, symbol, direction, entry, stop, [t for t in targets if t], ["extreme funding", "rising OI", "stalled extension", "taker divergence"], regime)

    def order_flow_imbalance_continuation(self, venue, symbol, f, s, state, peers, regime):
        if f.get("ofi_zscore") <= 2 or f.get("same_side_depth") <= 1.4 * max(f.get("adverse_depth"), 1e-9):
            return None
        direction = Direction.LONG if f.get("order_book_imbalance") > 0 else Direction.SHORT
        if s.trend_alignment not in {Direction.FLAT, direction}:
            return None
        entry = f.get("microprice") or f.get("mid_price")
        stop = entry - f.get("atr") if direction == Direction.LONG else entry + f.get("atr")
        target = entry + 2 * f.get("atr") if direction == Direction.LONG else entry - 2 * f.get("atr")
        return self._build_signal("order_flow_imbalance_continuation", venue, symbol, direction, entry, stop, [target], ["OFI z-score > 2", "thin book continuation", "microprice lead"], regime)

    def aggressor_exhaustion_absorption_fade(self, venue, symbol, f, s, state, peers, regime):
        muted_progress = abs((f.get("mid_price") - f.get("rolling_vwap"))) < 0.5 * max(f.get("atr"), 1e-9)
        if abs(f.get("cvd")) < self.config["strategies"]["aggressor_exhaustion_absorption_fade"]["cvd_extreme"] or not muted_progress or f.get("delta_oi") < 0:
            return None
        direction = Direction.LONG if s.bullish_sweep or s.bullish_order_block_active else Direction.SHORT if s.bearish_sweep or s.bearish_order_block_active else Direction.FLAT
        if direction == Direction.FLAT:
            return None
        entry = f.get("mid_price")
        stop = entry - f.get("atr") if direction == Direction.LONG else entry + f.get("atr")
        targets = [f.get("session_vwap"), f.get("poc")]
        return self._build_signal("aggressor_exhaustion_absorption_fade", venue, symbol, direction, entry, stop, [t for t in targets if t], ["CVD extreme", "absorption shelf", "microprice divergence", "OI not flushing"], regime)

    def fresh_oi_breakout_continuation(self, venue, symbol, f, s, state, peers, regime):
        if f.get("delta_oi") <= self.config["strategies"]["fresh_oi_breakout_continuation"]["delta_oi_min"] or abs(f.get("premium_zscore")) >= self.config["strategies"]["fresh_oi_breakout_continuation"]["premium_z_max"]:
            return None
        recent = state.view(venue, symbol).closes[-20:]
        if len(recent) < 10:
            return None
        high, low = max(recent[:-1]), min(recent[:-1])
        price = recent[-1]
        if price > high:
            direction = Direction.LONG
            stop = high - f.get("atr")
            target = price + (high - low) * 1.5
        elif price < low:
            direction = Direction.SHORT
            stop = low + f.get("atr")
            target = price - (high - low) * 1.5
        else:
            return None
        return self._build_signal("fresh_oi_breakout_continuation", venue, symbol, direction, price, stop, [target], ["range break", "fresh OI", "premium widening", "no absorption"], regime)

    def single_venue_premium_snapback(self, venue, symbol, f, s, state, peers, regime):
        if abs(f.get("premium_zscore")) < 2 or abs(f.get("delta_oi")) > self.config["strategies"]["single_venue_premium_snapback"]["delta_oi_abs_max"]:
            return None
        direction = Direction.SHORT if f.get("premium") > 0 else Direction.LONG
        entry = f.get("mark_price")
        stop = entry + 0.75 * f.get("atr") if direction == Direction.SHORT else entry - 0.75 * f.get("atr")
        midpoint = mean([f.get("mark_price"), f.get("index_price")]) if f.get("index_price") else entry
        target2 = f.get("index_price") or midpoint
        return self._build_signal("single_venue_premium_snapback", venue, symbol, direction, entry, stop, [midpoint, target2], ["premium z-score > 2", "spot/index not confirming", "OI flat/falling", "taker decelerating"], regime)

    def cross_venue_basis_dispersion_convergence(self, venue, symbol, f, s, state, peers, regime):
        peer_premia = [p.get("premium") for p in peers.values() if p.get("premium")]
        if len(peer_premia) < 2 or abs(f.get("premium") - mean(peer_premia)) < self.config["strategies"]["cross_venue_basis_dispersion_convergence"]["premium_gap_min"]:
            return None
        direction = Direction.SHORT if f.get("premium") > mean(peer_premia) else Direction.LONG
        entry = f.get("mark_price") or f.get("mid_price")
        stop = entry + f.get("atr") if direction == Direction.SHORT else entry - f.get("atr")
        target = (f.get("index_price") or entry) + (mean(peer_premia) if direction == Direction.LONG else -mean(peer_premia))
        return self._build_signal("cross_venue_basis_dispersion_convergence", venue, symbol, direction, entry, stop, [target], ["venue premium outlier", "spot stable", "tradable spread", "local OI/funding outlier"], regime)

    def spot_index_lead_follow_through(self, venue, symbol, f, s, state, peers, regime):
        gap = f.get("index_price") - f.get("mark_price")
        if abs(gap) < self.config["strategies"]["spot_index_lead_follow_through"]["lag_gap_min"] or abs(f.get("premium_zscore")) > 1.5:
            return None
        direction = Direction.LONG if gap > 0 and f.get("order_book_imbalance") > 0 else Direction.SHORT if gap < 0 and f.get("order_book_imbalance") < 0 else Direction.FLAT
        if direction == Direction.FLAT:
            return None
        entry = f.get("mid_price")
        stop = entry - f.get("atr") if direction == Direction.LONG else entry + f.get("atr")
        target = entry + 0.8 * abs(gap) if direction == Direction.LONG else entry - 0.8 * abs(gap)
        return self._build_signal("spot_index_lead_follow_through", venue, symbol, direction, entry, stop, [target], ["spot/index impulse", "perp lag", "premium neutral", "OFI aligned"], regime)

    def funding_window_inventory_rebalance(self, venue, symbol, f, s, state, peers, regime):
        if abs(f.get("funding_rate")) < self.config["strategies"]["funding_window_inventory_rebalance"]["funding_abs_min"] or f.get("open_interest") <= self.config["strategies"]["funding_window_inventory_rebalance"]["open_interest_min"]:
            return None
        direction = Direction.LONG if f.get("trade_delta") > 0 and f.get("order_book_imbalance") > 0 else Direction.SHORT if f.get("trade_delta") < 0 and f.get("order_book_imbalance") < 0 else Direction.FLAT
        if direction == Direction.FLAT:
            return None
        entry = f.get("mid_price")
        stop = entry - f.get("atr") if direction == Direction.LONG else entry + f.get("atr")
        target = f.get("rolling_vwap")
        return self._build_signal("funding_window_inventory_rebalance", venue, symbol, direction, entry, stop, [target], ["non-zero funding", "elevated OI", "post-funding imbalance", "spread normalized"], regime)

    def deribit_iv_shock_repricing(self, venue, symbol, f, s, state, peers, regime):
        if venue != "deribit":
            return None
        atm_iv = abs(f.get("option_atm_iv"))
        skew = abs(f.get("option_put_call_skew"))
        if atm_iv < self.config["strategies"]["deribit_iv_shock_repricing"]["iv_proxy_min"] and skew < self.config["strategies"]["deribit_iv_shock_repricing"].get("skew_abs_min", 0.05):
            return None
        direction = Direction.LONG if f.get("premium") > 0 and f.get("delta_oi") >= 0 else Direction.SHORT if f.get("premium") < 0 and f.get("delta_oi") <= 0 else Direction.FLAT
        if direction == Direction.FLAT:
            return None
        entry = f.get("mark_price") or f.get("mid_price")
        stop = entry - f.get("atr") if direction == Direction.LONG else entry + f.get("atr")
        target = entry + 1.2 * f.get("atr") if direction == Direction.LONG else entry - 1.2 * f.get("atr")
        return self._build_signal("deribit_iv_shock_repricing", venue, symbol, direction, entry, stop, [target], ["ATM IV shock", "options skew dislocation", "perp lagging", "benchmark lagging"], regime, metadata={"atm_iv": atm_iv, "put_call_skew": skew})
