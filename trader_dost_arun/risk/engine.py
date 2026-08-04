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

    def restore_state(self, saved: dict) -> None:
        """Rehydrate risk state from a checkpoint written before a restart.

        The kill switch and consecutive-loss counter are a LATCH: they must
        survive both restarts AND the UTC day boundary, otherwise a bot that hit
        its loss brake at 23:59 would silently resume signaling at 00:01 with no
        operator action. Only the *daily PnL* accumulators reset at the day
        boundary; the brake stays engaged until an operator explicitly resets it
        (see reset_kill_switch()). The day-scoped PnL fields are still only
        restored when the checkpoint is from the current UTC day.
        """
        if not saved:
            return
        # The latch is restored regardless of day - it is deliberately NOT
        # gated on the saved day matching today.
        self.kill_switch_active = bool(saved.get("kill_switch_active", False))
        self.consecutive_losses = int(saved.get("consecutive_losses", self.consecutive_losses))
        saved_day = saved.get("day")
        today = datetime.now(timezone.utc).date().isoformat()
        if saved_day != today:
            return
        self.daily_realized_r = float(saved.get("daily_realized_r", 0.0))
        self.daily_slippage_cost = float(saved.get("daily_slippage_cost", 0.0))

    def reset_kill_switch(self) -> None:
        """Operator-only latch release. Clears the consecutive-loss counter."""
        self.kill_switch_active = False
        self.consecutive_losses = 0

    def maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_day:
            # Day boundary resets the DAILY PnL accumulators only. The kill
            # switch and consecutive-loss latch intentionally carry across the
            # boundary so a loss limit can't be dodged by the clock.
            self.daily_realized_r = 0.0
            self.daily_slippage_cost = 0.0
            self.last_reset_day = today

    def is_valid_signal(self, signal: Signal) -> tuple[bool, str | None]:
        """Reject degenerate signals BEFORE sizing/risk math runs on them.

        A signal with entry <= 0, stop == entry (risk_per_unit == 0), a stop on
        the wrong side of entry, or no positive-target would poison every R
        downstream via register_outcome()'s divide-by-max(risk,1e-9). Fail closed.
        """
        entry, stop = float(signal.entry), float(signal.stop)
        direction = signal.direction.value
        if not (entry == entry) or entry <= 0 or not (stop == stop):  # NaN / non-positive entry
            return False, "invalid_price"
        if direction not in ("long", "short"):
            return False, "invalid_direction"
        targets = [float(t) for t in signal.targets if t and t == t]
        if direction == "long":
            if not (stop < entry):
                return False, "stop_not_below_entry"
            if not targets or max(targets) <= entry:
                return False, "no_upside_target"
        else:  # short
            if not (stop > entry):
                return False, "stop_not_above_entry"
            if not targets or min(targets) >= entry:
                return False, "no_downside_target"
        if abs(entry - stop) <= max(entry, 1.0) * 1e-9:
            return False, "degenerate_risk_range"
        return True, None

    def refine_signal(self, signal: Signal, atr: float, strategy_cfg: dict) -> Signal:
        atr = max(float(atr or 0.0), 0.0)
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
        # Reject degenerate positions rather than divide by ~0 and poison
        # daily_realized_r / consecutive_losses / Kelly inputs. A position whose
        # stop == entry has no defined R and must never be counted as a win or
        # loss; it is simply closed out with realized_r = 0.
        if position.signal.risk_per_unit <= max(abs(float(position.signal.entry)), 1.0) * 1e-9:
            position.exit_price = exit_price
            position.realized_r_multiple = 0.0
            position.outcome = 0
            position.closed_at = datetime.now(timezone.utc)
            return
        risk = position.signal.risk_per_unit
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
