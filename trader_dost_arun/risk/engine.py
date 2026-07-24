from __future__ import annotations

from datetime import datetime, timezone

from trader_dost_arun.core.models import HypotheticalPosition, Signal


class RiskEngine:
    def __init__(self, config: dict):
        self.config = config
        self.daily_realized_r = 0.0
        self.daily_slippage_cost = 0.0
        self.consecutive_losses = 0
        self.kill_switch_active = False
        self.last_reset_day = datetime.now(timezone.utc).date()

    def maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_day:
            self.daily_realized_r = 0.0
            self.daily_slippage_cost = 0.0
            self.consecutive_losses = 0
            self.kill_switch_active = False
            self.last_reset_day = today

    def refine_signal(self, signal: Signal, atr: float, strategy_cfg: dict) -> Signal:
        mult = strategy_cfg.get("atr_stop_multiplier", 1.0)
        if signal.direction.value == "long":
            signal.stop = min(signal.stop, signal.entry - atr * mult)
            if not signal.targets:
                signal.targets = [signal.entry + atr * strategy_cfg.get("target_multiple", 1.5)]
        else:
            signal.stop = max(signal.stop, signal.entry + atr * mult)
            if not signal.targets:
                signal.targets = [signal.entry - atr * strategy_cfg.get("target_multiple", 1.5)]
        return signal

    def allow_new_signal(self) -> tuple[bool, str | None]:
        self.maybe_reset()
        if self.kill_switch_active:
            return False, "kill_switch_active"
        if self.daily_realized_r <= -abs(self.config["risk"]["daily_loss_limit_r"]):
            return False, "daily_hypothetical_loss_limit"
        return True, None

    def register_outcome(self, position: HypotheticalPosition, exit_price: float) -> None:
        risk = max(position.signal.risk_per_unit, 1e-9)
        fill_price = position.fill_price or position.signal.entry
        realized = (exit_price - fill_price) / risk if position.signal.direction.value == "long" else (fill_price - exit_price) / risk
        realized -= abs(position.funding_cost) / risk
        position.exit_price = exit_price
        position.realized_r_multiple = realized
        position.outcome = 1 if realized > 0 else 0
        position.closed_at = datetime.now(timezone.utc)
        theoretical = (exit_price - position.signal.entry) / risk if position.signal.direction.value == "long" else (position.signal.entry - exit_price) / risk
        self.daily_slippage_cost += max(theoretical - realized, 0.0)
        self.daily_realized_r += realized
        self.consecutive_losses = 0 if realized > 0 else self.consecutive_losses + 1
        if self.consecutive_losses >= self.config["risk"]["kill_switch_after_consecutive_losses"]:
            self.kill_switch_active = True
