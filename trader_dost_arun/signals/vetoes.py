from __future__ import annotations

from datetime import datetime, timezone

from trader_dost_arun.core.models import Direction, FeatureSet, StructuralState
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.newsguard.models import ImpactAssessment


class VetoEngine:
    def __init__(self, config: dict):
        self.config = config

    def evaluate(self, strategy_name: str, venue: str, symbol: str, features: FeatureSet, structural: StructuralState, state: MarketStateStore, external: ExternalContext, peer_features: dict[str, FeatureSet], minutes_to_funding: float | None = None, news_assessment: ImpactAssessment | None = None) -> tuple[dict[str, bool], str | None]:
        checks = {
            "stale_snapshot": self._stale_snapshot(venue, symbol, features, state),
            "spread_depth_deterioration": self._spread_depth_veto(venue, symbol, features, state),
            "wrong_leverage_regime": self._wrong_leverage_regime(strategy_name, features),
            "volatility_anomaly": self._volatility_anomaly(strategy_name, features),
            "exchange_instability": self._exchange_instability(features),
            "macro_release_window": not (external.macro_blocked or external.sec_blocked),
            "correlation_spike": self._correlation_spike(symbol, features, peer_features, external),
            "cross_venue_dispersion": self._cross_venue_dispersion(features),
            "stablecoin_liquidity_stress": self._stablecoin_stress(strategy_name, external),
            "funding_timestamp_proximity": self._funding_proximity(strategy_name, minutes_to_funding),
            "liquidation_tape_against_setup": self._liquidation_tape(strategy_name, features, structural),
            "news_guard": not bool(news_assessment and (news_assessment.suppress or news_assessment.delay_seconds > 0)),
        }
        failed = [name for name, allowed in checks.items() if not allowed]
        return checks, failed[0] if failed else None

    def _stale_snapshot(self, venue: str, symbol: str, features: FeatureSet, state: MarketStateStore) -> bool:
        max_age_seconds = float(self.config["vetoes"]["exchange_instability"].get("max_feed_lag_seconds", 2))
        age_ok = (datetime.now(timezone.utc) - features.timestamp).total_seconds() <= max_age_seconds
        local_view = state.view(venue, symbol)
        if not local_view.snapshots:
            return age_ok
        min_sources = int(self.config["vetoes"].get("freshness_quorum", {}).get("min_sources", 2))
        freshness = state.freshness(venue, symbol, max_age_seconds=max_age_seconds, min_sources=min_sources)
        own_age = freshness.own_age_seconds if freshness.own_age_seconds is not None else float("inf")
        return age_ok and own_age <= max_age_seconds and freshness.quorum_met

    def _spread_depth_veto(self, venue: str, symbol: str, features: FeatureSet, state: MarketStateStore) -> bool:
        spread = features.get("spread")
        same_side_depth = features.get("same_side_depth")
        spread_pct = state.spread_percentile(venue, symbol, spread)
        depth_pct = state.same_side_depth_percentile(venue, symbol, same_side_depth)
        slippage_proxy = spread + spread * (0.5 if same_side_depth <= 0 else 1 / max(same_side_depth, 1))
        target_proxy = max(features.get("atr") * 1.5, 1e-9)
        return not (spread_pct > 0.90 or depth_pct < 0.25 or slippage_proxy > 0.35 * target_proxy)

    def _wrong_leverage_regime(self, strategy_name: str, features: FeatureSet) -> bool:
        continuation = {"liquidation_cascade_continuation", "order_flow_imbalance_continuation", "fresh_oi_breakout_continuation", "spot_index_lead_follow_through", "funding_window_inventory_rebalance", "deribit_iv_shock_repricing"}
        reversion = {"extreme_funding_crowding_reversion", "aggressor_exhaustion_absorption_fade", "single_venue_premium_snapback", "cross_venue_basis_dispersion_convergence"}
        delta_oi = features.get("delta_oi")
        funding_z = abs(features.get("funding_zscore"))
        if strategy_name in continuation:
            return delta_oi > 0 or strategy_name == "liquidation_cascade_continuation"
        if strategy_name in reversion:
            return funding_z >= 1.5 or abs(features.get("premium_zscore")) >= 1.5 or delta_oi <= 0
        return True

    def _volatility_anomaly(self, strategy_name: str, features: FeatureSet) -> bool:
        return strategy_name == "liquidation_cascade_continuation" or features.get("realized_vol_5m") <= self.config["vetoes"]["volatility_anomaly"]["rv_5m_max"]

    def _exchange_instability(self, features: FeatureSet) -> bool:
        mark = features.get("mark_price")
        index = features.get("index_price")
        if index == 0:
            return False
        gap_sigma_limit = self.config["vetoes"]["exchange_instability"]["max_mark_index_gap_bps"] / 10000
        lag_ok = (datetime.now(timezone.utc) - features.timestamp).total_seconds() <= self.config["vetoes"]["exchange_instability"]["max_feed_lag_seconds"]
        return abs(mark - index) / abs(index) <= gap_sigma_limit and lag_ok

    def _correlation_spike(self, symbol: str, features: FeatureSet, peer_features: dict[str, FeatureSet], external: ExternalContext) -> bool:
        del peer_features
        if symbol in {"BTCUSDT", "ETHUSDT", "BTC-PERP", "ETH-PERP", "BTC-USDT-SWAP", "ETH-USDT-SWAP"}:
            return True
        btc_vol = abs((external.benchmark_returns or {}).get("BTC", 0.0))
        return not (btc_vol > 3 and features.get("price_dispersion") > self.config["vetoes"]["correlation_spike"]["dispersion_limit"])

    def _cross_venue_dispersion(self, features: FeatureSet) -> bool:
        return features.get("price_dispersion") <= self.config["vetoes"]["cross_venue_dispersion"]["price_dispersion_limit"] and features.get("premium_dispersion") <= self.config["vetoes"]["cross_venue_dispersion"]["premium_dispersion_limit"]

    def _stablecoin_stress(self, strategy_name: str, external: ExternalContext) -> bool:
        return strategy_name == "liquidation_cascade_continuation" or not external.stablecoin_stress

    def _funding_proximity(self, strategy_name: str, minutes_to_funding: float | None) -> bool:
        if strategy_name == "funding_window_inventory_rebalance" or minutes_to_funding is None:
            return True
        cfg = self.config["vetoes"]["funding_proximity"]
        return not (-cfg["post_minutes"] <= minutes_to_funding <= cfg["pre_minutes"])

    def _liquidation_tape(self, strategy_name: str, features: FeatureSet, structural: StructuralState) -> bool:
        fade_strategies = {"extreme_funding_crowding_reversion", "aggressor_exhaustion_absorption_fade", "single_venue_premium_snapback", "cross_venue_basis_dispersion_convergence"}
        if strategy_name not in fade_strategies:
            return True
        liq = features.get("liquidation_notional")
        delta_oi = features.get("delta_oi")
        if liq <= self.config["vetoes"]["liquidation_tape"]["liquidation_notional_limit"]:
            return True
        if structural.trend_alignment == Direction.SHORT:
            return delta_oi >= 0
        if structural.trend_alignment == Direction.LONG:
            return delta_oi <= 0
        return False
