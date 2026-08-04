from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from trader_dost_arun.core.models import Direction


@dataclass(slots=True)
class SlippageModel:
    mode: str = "realistic"

    def _params(self) -> tuple[float, float]:
        if self.mode == "conservative":
            return 5.0, 1.0
        if self.mode == "aggressive":
            return 1.0, 0.25
        return 2.0, 0.5

    def slippage_bps(self, quantity: float, same_side_depth: float, funding_proximity_bonus: float = 0.0) -> float:
        base_bps, k = self._params()
        return base_bps + k * sqrt(max(quantity, 0.0) / max(same_side_depth, 1e-9)) + max(funding_proximity_bonus, 0.0)

    def expected_fill_price(
        self,
        entry: float,
        direction: Direction,
        spread: float,
        quantity: float,
        same_side_depth: float,
        funding_proximity_bonus: float = 0.0,
    ) -> tuple[float, float]:
        slip_bps = self.slippage_bps(quantity, same_side_depth, funding_proximity_bonus)
        adverse = 0.5 * spread + entry * slip_bps / 10_000
        if direction == Direction.LONG:
            return entry + adverse, slip_bps
        return entry - adverse, slip_bps
