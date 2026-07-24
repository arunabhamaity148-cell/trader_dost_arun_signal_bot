from __future__ import annotations

from collections import defaultdict

from trader_dost_arun.core.models import HypotheticalPosition, Signal
from trader_dost_arun.core.persistence import PositionStore


class ExposureOptimizer:
    def __init__(self, max_gross_exposure: float = 0.1, max_same_direction: float = 0.06, position_store: PositionStore | None = None) -> None:
        self.max_gross_exposure = max_gross_exposure
        self.max_same_direction = max_same_direction
        self.position_store = position_store
        self.positions: list[HypotheticalPosition] = position_store.load_open_positions() if position_store else []

    def add_position(self, position: HypotheticalPosition) -> None:
        self.positions.append(position)
        if self.position_store is not None:
            self.position_store.save_position(position)

    def close_position(self, symbol: str, venue: str | None = None, exit_price: float = 0.0, realized_r: float = 0.0, exit_reason: str = "closed") -> None:
        remaining: list[HypotheticalPosition] = []
        for position in self.positions:
            matched = position.signal.symbol == symbol and (venue is None or position.signal.venue == venue)
            if matched and position.closed_at is not None and self.position_store is not None:
                self.position_store.close_position(symbol, position.signal.venue, exit_price, realized_r, exit_reason)
                continue
            if matched and position.closed_at is None:
                continue
            remaining.append(position)
        self.positions = remaining

    def evaluate(self, signal: Signal, correlations: dict[str, float]) -> tuple[bool, float]:
        open_positions = [p for p in self.positions if p.closed_at is None]
        gross = sum(p.signal.advisory_size_fraction for p in open_positions)
        direction_bucket = defaultdict(float)
        for position in open_positions:
            direction_bucket[position.signal.direction.value] += position.signal.advisory_size_fraction
        correlation_penalty = max(correlations.get(signal.symbol, 0.0), correlations.get("BTC", 0.0), correlations.get("ETH", 0.0))
        proposed = signal.advisory_size_fraction * max(0.2, 1 - correlation_penalty)
        same_dir = direction_bucket[signal.direction.value] + proposed
        allow = (gross + proposed) <= self.max_gross_exposure and same_dir <= self.max_same_direction
        return allow, proposed
