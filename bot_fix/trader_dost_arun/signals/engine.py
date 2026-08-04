from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from trader_dost_arun.adaptive.bayesian import BayesianConfidenceModel
from trader_dost_arun.adaptive.exposure import ExposureOptimizer
from trader_dost_arun.adaptive.feature_importance import OnlineFeatureImportanceTracker
from trader_dost_arun.adaptive.kelly import BoundedKellySizer
from trader_dost_arun.adaptive.meta_label import MetaLabelModel
from trader_dost_arun.adaptive.regime import HMMRegimeDetector
from trader_dost_arun.core.checkpoint import StateCheckpoint
from trader_dost_arun.core.models import Direction, FeatureSet, HypotheticalPosition, Signal
from trader_dost_arun.core.persistence import PositionStore
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.execution.slippage import SlippageModel
from trader_dost_arun.features.structural import build_structural_state
from trader_dost_arun.newsguard.guard import NewsGuard
from trader_dost_arun.risk.engine import RiskEngine
from trader_dost_arun.signals.deterministic import DeterministicStrategyEngine
from trader_dost_arun.signals.vetoes import VetoEngine


class SignalEngine:
    CONTINUATION = {
        "liquidation_cascade_continuation",
        "order_flow_imbalance_continuation",
        "fresh_oi_breakout_continuation",
        "spot_index_lead_follow_through",
        "funding_window_inventory_rebalance",
        "deribit_iv_shock_repricing",
    }
    REVERSION = {
        "extreme_funding_crowding_reversion",
        "aggressor_exhaustion_absorption_fade",
        "single_venue_premium_snapback",
        "cross_venue_basis_dispersion_convergence",
    }

    def __init__(self, config: dict, news_guard: NewsGuard | None = None, position_store: PositionStore | None = None, operator_state=None):
        self.config = config
        # Shared operator-toggles object. When app.py constructs us it passes
        # the same OperatorState the TelegramAdminBot writes to, so /pause and
        # /resume reach the live signal path. Falls back to a console-default
        # instance for tests so nothing here requires wiring.
        self._operator_state = operator_state
        self.vetoes = VetoEngine(config)
        self.strategies = DeterministicStrategyEngine(config)
        self.risk = RiskEngine(config)
        self.kelly = BoundedKellySizer(config["adaptive"]["kelly_cap"], config["adaptive"]["kelly_fraction"])
        self.regimes: dict[str, HMMRegimeDetector] = defaultdict(
            lambda: HMMRegimeDetector(
                config["adaptive"]["hmm_regimes"],
                config["adaptive"].get("hmm_min_samples", 500),
                config["adaptive"].get("hmm_refit_seconds", 300),
                config["adaptive"].get("hmm_transition_confirmation_ticks", 3),
            )
        )
        self.bayes = BayesianConfidenceModel(config["strategy_priors"], prior_strength=float(config["adaptive"].get("prior_strength", 10)))
        self.meta = MetaLabelModel(config["adaptive"]["meta_label_threshold"])
        self.importance = OnlineFeatureImportanceTracker()
        self.position_store = position_store or PositionStore(config.get("positions", {}).get("db_path", "./data/positions.sqlite3"))
        self.exposure = ExposureOptimizer(config["adaptive"]["max_gross_exposure"], config["adaptive"]["max_same_direction_exposure"], position_store=self.position_store)
        self.news_guard = news_guard
        self.slippage = SlippageModel(config.get("execution", {}).get("slippage_mode", "realistic"))
        self.checkpoint = StateCheckpoint(config.get("checkpoint", {}).get("path", "./data/checkpoint.json"))
        # Rehydrate risk-engine state (kill switch, daily loss, consecutive
        # losses) from the last checkpoint written before this process
        # started/restarted. See RiskEngine.restore_state for why this
        # matters: without it, a restart silently wipes the safety brake.
        self.risk.restore_state(self.checkpoint.load_latest().get("risk", {}))

    async def update_open_positions(self, venue: str, symbol: str, state: MarketStateStore) -> list[HypotheticalPosition]:
        latest = state.view(venue, symbol).latest
        if latest is None or latest.mid_price is None:
            return []
        latest_price = latest.mid_price
        closed: list[HypotheticalPosition] = []
        for position in list(self.exposure.positions):
            if position.closed_at is not None:
                continue
            if position.signal.symbol != symbol or position.signal.venue != venue:
                continue
            stop_hit = latest_price <= position.signal.stop if position.signal.direction == Direction.LONG else latest_price >= position.signal.stop
            target_price = position.signal.targets[0] if position.signal.targets else position.signal.entry
            target_hit = latest_price >= target_price if position.signal.direction == Direction.LONG else latest_price <= target_price
            if not stop_hit and not target_hit:
                continue
            exit_price = position.signal.stop if stop_hit else target_price
            position.exit_reason = "stop" if stop_hit else "target"
            self.risk.register_outcome(position, exit_price)
            state.update_performance(position.signal.strategy_name, position.realized_r_multiple or 0.0)
            self.bayes.update(position.signal.strategy_name, position.signal.regime, int(position.outcome or 0))
            feature_row = position.signal.metadata.get("feature_row")
            if feature_row:
                self.meta.partial_fit([feature_row], [int(position.outcome or 0)], strategy=position.signal.strategy_name)
            feature_map = position.signal.metadata.get("feature_map")
            if feature_map:
                self.importance.update(feature_map, int(position.outcome or 0))
            await self.exposure._close_position_async(position)
            closed.append(position)
        if closed:
            self._save_checkpoint()
        return closed

    def _save_checkpoint(self) -> None:
        self.checkpoint.save(
            {
                "day": datetime.now(timezone.utc).date().isoformat(),
                "risk": {
                    "daily_realized_r": self.risk.daily_realized_r,
                    "daily_slippage_cost": self.risk.daily_slippage_cost,
                    "consecutive_losses": self.risk.consecutive_losses,
                    "kill_switch_active": self.risk.kill_switch_active,
                },
                "positions": len([p for p in self.exposure.positions if p.closed_at is None]),
            }
        )

    def _has_open_position(self, strategy_name: str, symbol: str, venue: str) -> bool:
        return any(
            p.closed_at is None
            and p.signal.strategy_name == strategy_name
            and p.signal.symbol == symbol
            and p.signal.venue == venue
            for p in self.exposure.positions
        )

    def _regime_weight(self, strategy_name: str, regime: str) -> tuple[str, float, float]:
        if regime == "trending":
            if strategy_name in self.CONTINUATION:
                return "up-weighted", 1.2, 1.2
            if strategy_name in self.REVERSION:
                return "down-weighted", 0.72, 0.85
        if regime == "mean_reverting":
            if strategy_name in self.REVERSION:
                return "up-weighted", 1.15, 1.1
            if strategy_name in self.CONTINUATION:
                return "down-weighted", 0.78, 0.9
        if regime == "high_stress":
            if strategy_name == "liquidation_cascade_continuation":
                return "up-weighted", 1.35, 1.4
            if strategy_name in {"order_flow_imbalance_continuation", "fresh_oi_breakout_continuation"}:
                return "down-weighted", 0.65, 0.8
            return "down-weighted", 0.5, 0.7
        return "neutral", 1.0, 1.0

    async def evaluate(self, venue: str, symbol: str, features: FeatureSet, state: MarketStateStore, peer_features: dict[str, FeatureSet], external: ExternalContext) -> list[Signal]:
        allow, reason = self.risk.allow_new_signal()
        if not allow:
            return [Signal("system_block", symbol, venue, direction=Direction.FLAT, entry=0, stop=0, targets=[], confidence=0, advisory_size_fraction=0, regime="blocked", confirmations=[], vetoes_checked={}, suppressed_reason=reason)]
        detector = self.regimes[symbol]
        await detector.observe(features.get("realized_vol_5m"), features.get("trade_delta"), features.get("funding_rate"))
        regime_record = detector.current()
        structural = build_structural_state(state.view(venue, symbol), features.get("delta_oi"))
        news_assessment = await self.news_guard.assess(symbol, venue, features, state, external, regime_record.label) if self.news_guard else None
        candidates = self.strategies.evaluate_all(venue, symbol, features, structural, state, peer_features, regime_record.label)
        # Snapshot the shared pause set once per evaluation. This is the LIVE
        # read of /pause (previously this read getattr(news_guard,
        # "paused_strategies"), which was always [] because NewsGuard never
        # owned that state - the admin bot's writes lived on a different object).
        operator = self._operator_state
        paused_strategies = operator.paused_strategies() if (operator is not None and hasattr(operator, "paused_strategies")) else getattr(self.news_guard, "paused_strategies", [])
        paused_set = set(paused_strategies)
        accepted: list[Signal] = []
        for signal in candidates:
            if signal.strategy_name in paused_set:
                signal.suppressed_reason = "strategy_paused"
                state.suppression_counts["strategy_paused"] += 1
                continue
            weight_label, confidence_mult, priority_mult = self._regime_weight(signal.strategy_name, regime_record.label)
            if priority_mult < 0.55:
                signal.suppressed_reason = "regime_gate"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            vetoes_checked, failed = self.vetoes.evaluate(signal.strategy_name, venue, symbol, features, structural, state, external, peer_features, news_assessment=news_assessment)
            signal.vetoes_checked = vetoes_checked
            if failed:
                signal.suppressed_reason = failed
                state.suppression_counts[failed] += 1
                continue
            if structural.contradicts(signal.direction):
                signal.suppressed_reason = "structural_contradiction"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            if self._has_open_position(signal.strategy_name, signal.symbol, signal.venue):
                # Without this, the exact same strategy could re-fire on the
                # exact same symbol+venue on the very next evaluation tick
                # (every signal_evaluation_interval_seconds) while a position
                # it already opened is still live - exposure.evaluate() only
                # caps aggregate portfolio size/direction, it never checks
                # for this specific duplicate. That meant the same setup
                # could alert repeatedly while you were already in the
                # trade, encouraging a repeat entry into a position you
                # already hold.
                signal.suppressed_reason = "duplicate_open_position"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            perf = state.performances[signal.strategy_name]
            raw_kelly = self.kelly.size(perf)
            mean_confidence, lower_conf = self.bayes.confidence(signal.strategy_name, regime_record.label)
            meta_row = [features.get("spread"), features.get("same_side_depth"), features.get("realized_vol_1m"), features.get("delta_oi"), perf.win_rate, perf.payoff_ratio]
            meta_prob = self.meta.predict_probability(meta_row, strategy=signal.strategy_name)
            if meta_prob < self.config["adaptive"]["meta_label_threshold"]:
                signal.suppressed_reason = "meta_label_rejected"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            news_conf_mult = news_assessment.confidence_multiplier if news_assessment else 1.0
            risk_mult = news_assessment.risk_multiplier if news_assessment else 1.0
            calibrated_conf = max(lower_conf, mean_confidence * meta_prob * confidence_mult * news_conf_mult)
            signal.confidence = calibrated_conf
            signal.metadata["meta_probability"] = meta_prob
            signal.metadata["structural"] = structural.details
            signal.metadata["regime_weighting"] = weight_label
            signal.metadata["regime_weight"] = priority_mult
            signal.metadata["news_guard_reasons"] = news_assessment.reasons if news_assessment else []
            signal.metadata["bayesian_confidence"] = mean_confidence
            signal.metadata["calibrated_confidence"] = calibrated_conf
            signal.metadata["live_win_rate"] = perf.win_rate * 100
            signal.metadata["live_samples"] = perf.sample_size
            signal = self.risk.refine_signal(signal, features.get("atr"), self.config["strategies"].get(signal.strategy_name, {}))
            # Fail-closed: reject any degenerate signal (entry<=0, stop==entry,
            # stop on the wrong side, no upside target) BEFORE sizing so a bad
            # strategy output can never produce a garbage R or an unsafe alert.
            valid, invalid_reason = self.risk.is_valid_signal(signal)
            if not valid:
                signal.suppressed_reason = f"invalid_signal:{invalid_reason}"
                state.suppression_counts["invalid_signal"] += 1
                continue
            fill_price, slippage_bps = self.slippage.expected_fill_price(signal.entry, signal.direction, features.get("spread"), max(signal.advisory_size_fraction, 0.01), features.get("same_side_depth"))
            effective_reward = abs((signal.targets[0] if signal.targets else signal.entry) - fill_price)
            effective_risk = abs(fill_price - signal.stop)
            if effective_reward / max(effective_risk, 1e-9) < 1.0:
                signal.suppressed_reason = "slippage_invalidates_rr"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            edge = max(0.0, (signal.confidence / 100 - 0.5) / 0.3)
            signal.advisory_size_fraction = raw_kelly * edge
            signal.metadata["expected_fill_price"] = fill_price
            signal.metadata["slippage_bps"] = slippage_bps
            signal.metadata["confluence_score"] = min(10, len(signal.confirmations))
            signal.metadata["feature_row"] = meta_row
            numeric_features = {k: float(v) for k, v in features.values.items() if isinstance(v, (int, float, bool))}
            signal.metadata["feature_map"] = numeric_features
            allowed, scaled_size = self.exposure.evaluate(signal, {symbol: features.get("price_dispersion")})
            if not allowed:
                signal.suppressed_reason = "portfolio_exposure_limit"
                state.suppression_counts[signal.suppressed_reason] += 1
                continue
            signal.advisory_size_fraction = scaled_size / max(risk_mult, 1.0)
            signal.metadata["priority_score"] = signal.confidence * priority_mult
            # Compute the model-side leverage once and mirror it into metadata so
            # the advisory template and the internal HypotheticalPosition can no
            # longer disagree. Fixes "Display shows 5x while the model uses 1.0x".
            from trader_dost_arun.ops.alerts import advisory_leverage
            model_leverage = float(advisory_leverage(signal))
            signal.metadata["leverage"] = model_leverage
            position = HypotheticalPosition(signal=signal, leverage=model_leverage, fill_price=fill_price)
            # Persist off the event loop so this SQLite write never stalls signal
            # production on a slow disk.
            await self.exposure.add_position_async(position)
            accepted.append(signal)
        if accepted:
            # Persist risk/kill-switch state once per evaluation that produced
            # a position (not per candidate). The checkpoint write is cheap but
            # synchronous; keep it out of the per-signal hot loop.
            self._save_checkpoint()
        return sorted(accepted, key=lambda item: item.metadata.get("priority_score", item.confidence), reverse=True)

    def engine_stats(self) -> dict:
        """Small read-only snapshot for the admin bot's /status command."""
        return {
            "kill_switch_active": self.risk.kill_switch_active,
            "daily_realized_r": round(self.risk.daily_realized_r, 3),
            "consecutive_losses": self.risk.consecutive_losses,
            "open_positions": len([p for p in self.exposure.positions if p.closed_at is None]),
            "paused_strategies": self._operator_state.paused_strategies() if self._operator_state else [],
        }
