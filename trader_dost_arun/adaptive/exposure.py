from __future__ import annotations

from collections import defaultdict

from trader_dost_arun.core.models import HypotheticalPosition, Signal
from trader_dost_arun.core.persistence import PositionStore


class ExposureOptimizer:
    def __init__(self, max_gross_exposure: float = 0.1, max_same_direction: float = 0.06, position_store: PositionStore | None = None) -> None:
        self.max_gross_exposure = max_gross_exposure
        self.max_same_direction = max_same_direction
        self.position_store = position_store
        # The positions list is shared between the market-consumer task (which
        # closes positions on stop/target) and the scheduler evaluation task
        # (which adds positions). A lock keeps both sides consistent. SQLite
        # persistence happens off the event loop via to_thread.
        self._lock = None  # created lazily inside the running event loop
        self.positions: list[HypotheticalPosition] = []
        if position_store is not None:
            try:
                self.positions = position_store.load_open_positions()
            except Exception:
                self.positions = []

    def _get_lock(self) -> "asyncio.Lock":
        if self._lock is None:
            import asyncio
            self._lock = asyncio.Lock()
        return self._lock

    async def add_position_async(self, position: HypotheticalPosition) -> None:
        """Async-safe path for the running app: holds the lock while appending
        to self.positions and offloads the SQLite write to a worker thread so
        signal evaluation isn't blocked on disk. The in-memory append happens
        BEFORE the SQLite write completes so immediate downstream reads (e.g.
        update_open_positions on the very next tick) see the position."""
        async with self._get_lock():
            self.positions.append(position)
            store = self.position_store
            if store is not None:
                import asyncio as _asyncio

                # We deliberately DO NOT await the SQLite write here - it can
                # complete asynchronously. If the process crashes before the
                # write lands, the risk checkpoint (also async) may be partial,
                # which is safer than blocking the hot path.
                _asyncio.create_task(_asyncio.to_thread(store.save_position, position))

    def add_position(self, position: HypotheticalPosition) -> None:
        # Synchronous path for tests / backtest callers running without an event
        # loop, or for scripts that just want the behavior without the lock.
        self.positions.append(position)
        if self.position_store is not None:
            self.position_store.save_position(position)

    async def _close_position_async(self, position: HypotheticalPosition) -> None:
        async with self._get_lock():
            store = self.position_store
            if store is not None and position.db_id is not None:
                import asyncio
                await asyncio.to_thread(
                    store.close_position_by_id,
                    position.db_id,
                    position.exit_price if position.exit_price is not None else 0.0,
                    position.realized_r_multiple if position.realized_r_multiple is not None else 0.0,
                    position.exit_reason or "closed",
                )
            self.positions = [p for p in self.positions if p is not position]

    def close_position(self, position: HypotheticalPosition) -> None:
        # Sync path: used by tests and offline callers (non-running loop).
        if self.position_store is not None and position.db_id is not None:
            self.position_store.close_position_by_id(
                position.db_id,
                position.exit_price if position.exit_price is not None else 0.0,
                position.realized_r_multiple if position.realized_r_multiple is not None else 0.0,
                position.exit_reason or "closed",
            )
        self.positions = [p for p in self.positions if p is not position]

    def open_positions_snapshot(self) -> list[HypotheticalPosition]:
        # Read path consistent with writer path. Snapshot under a short GIL-safe
        # copy; inside a single event loop this is safe against asyncio reentrancy
        # because the only mutations are list rebinds, not in-place edits.
        return [p for p in self.positions if p.closed_at is None]

    def evaluate(self, signal: Signal, correlations: dict[str, float]) -> tuple[bool, float]:
        # Read the open set as of *this* evaluation tick. The list snapshot
        # prevents a concurrent _close_position_async rebinding self.positions mid-iteration
        # from silently dropping a position from this allow/deny computation.
        open_positions = self.open_positions_snapshot()
        gross = sum(p.signal.advisory_size_fraction for p in open_positions)
        direction_bucket = defaultdict(float)
        for position in open_positions:
            direction_bucket[position.signal.direction.value] += position.signal.advisory_size_fraction
        correlation_penalty = max(correlations.get(signal.symbol, 0.0), correlations.get("BTC", 0.0), correlations.get("ETH", 0.0))
        proposed = signal.advisory_size_fraction * max(0.2, 1 - correlation_penalty)
        same_dir = direction_bucket[signal.direction.value] + proposed
        allow = (gross + proposed) <= self.max_gross_exposure and same_dir <= self.max_same_direction
        return allow, proposed
