from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any

from trader_dost_arun.core.models import LiquidationEvent, MarketSnapshot, Trade


@dataclass(slots=True)
class QueueDropCounters:
    coalesced_snapshots: int = 0
    dropped_snapshots: int = 0
    dropped_trades: int = 0
    dropped_liquidations: int = 0

    @property
    def total_dropped(self) -> int:
        return self.dropped_snapshots + self.dropped_trades + self.dropped_liquidations


class BoundedMarketQueue:
    """Bounded queue with latest-state semantics for snapshots.

    Market snapshots are coalesced by venue+symbol so websocket readers do not block
    behind obsolete book updates. Trades and liquidations remain FIFO but are still
    bounded so memory usage cannot grow without limit.
    """

    def __init__(self, maxsize: int, snapshot_capacity_ratio: float = 0.7) -> None:
        self.maxsize = max(1, int(maxsize))
        ratio = min(max(float(snapshot_capacity_ratio), 0.1), 0.95)
        self._snapshot_capacity = max(1, int(self.maxsize * ratio))
        self._critical_capacity = max(1, self.maxsize - self._snapshot_capacity)
        self._critical: deque[Trade | LiquidationEvent] = deque()
        self._snapshots: OrderedDict[str, MarketSnapshot] = OrderedDict()
        self._condition = asyncio.Condition()
        self._prefer_snapshots = True
        self._drops = QueueDropCounters()

    def _snapshot_key(self, item: MarketSnapshot) -> str:
        return f"{item.venue}:{item.symbol}"

    def _current_size(self) -> int:
        return len(self._critical) + len(self._snapshots)

    def qsize(self) -> int:
        return self._current_size()

    def empty(self) -> bool:
        return self.qsize() == 0

    def task_done(self) -> None:
        return None

    def snapshot(self) -> dict[str, int]:
        return {
            "coalesced_snapshots": self._drops.coalesced_snapshots,
            "dropped_snapshots": self._drops.dropped_snapshots,
            "dropped_trades": self._drops.dropped_trades,
            "dropped_liquidations": self._drops.dropped_liquidations,
            "dropped_total": self._drops.total_dropped,
            "snapshot_depth": len(self._snapshots),
            "critical_depth": len(self._critical),
            "snapshot_capacity": self._snapshot_capacity,
            "critical_capacity": self._critical_capacity,
        }

    def _evict_oldest_snapshot(self) -> bool:
        if not self._snapshots:
            return False
        self._snapshots.popitem(last=False)
        self._drops.dropped_snapshots += 1
        return True

    def _evict_oldest_trade(self) -> bool:
        for index, item in enumerate(self._critical):
            if isinstance(item, Trade):
                del self._critical[index]
                self._drops.dropped_trades += 1
                return True
        return False

    def _evict_oldest_liquidation(self) -> bool:
        for index, item in enumerate(self._critical):
            if isinstance(item, LiquidationEvent):
                del self._critical[index]
                self._drops.dropped_liquidations += 1
                return True
        return False

    def _append_snapshot(self, item: MarketSnapshot) -> None:
        key = self._snapshot_key(item)
        if key in self._snapshots:
            self._snapshots[key] = item
            self._snapshots.move_to_end(key)
            self._drops.coalesced_snapshots += 1
            return
        if len(self._snapshots) >= self._snapshot_capacity or self._current_size() >= self.maxsize:
            if not self._evict_oldest_snapshot() and len(self._critical) >= self._critical_capacity:
                if self._evict_oldest_trade():
                    pass
                elif self._evict_oldest_liquidation():
                    pass
        self._snapshots[key] = item

    def _append_trade(self, item: Trade) -> None:
        if len(self._critical) >= self._critical_capacity or self._current_size() >= self.maxsize:
            if self._evict_oldest_snapshot():
                pass
            elif self._evict_oldest_trade():
                pass
            else:
                self._drops.dropped_trades += 1
                return
        self._critical.append(item)

    def _append_liquidation(self, item: LiquidationEvent) -> None:
        if len(self._critical) >= self._critical_capacity or self._current_size() >= self.maxsize:
            if self._evict_oldest_snapshot():
                pass
            elif self._evict_oldest_trade():
                pass
            elif self._evict_oldest_liquidation():
                pass
            else:
                self._drops.dropped_liquidations += 1
                return
        self._critical.append(item)

    async def put(self, item: Any) -> None:
        async with self._condition:
            if isinstance(item, MarketSnapshot):
                self._append_snapshot(item)
            elif isinstance(item, LiquidationEvent):
                self._append_liquidation(item)
            elif isinstance(item, Trade):
                self._append_trade(item)
            else:
                if self._current_size() >= self.maxsize and not self._evict_oldest_snapshot():
                    self._critical.popleft()
                self._critical.append(item)
            self._condition.notify()

    def _pop_snapshot(self) -> MarketSnapshot:
        _, item = self._snapshots.popitem(last=False)
        return item

    def _pop_critical(self) -> Trade | LiquidationEvent:
        return self._critical.popleft()

    async def get(self) -> Any:
        async with self._condition:
            while self._current_size() == 0:
                await self._condition.wait()
            if self._critical and self._snapshots:
                if self._prefer_snapshots:
                    item = self._pop_snapshot()
                else:
                    item = self._pop_critical()
                self._prefer_snapshots = not self._prefer_snapshots
                return item
            if self._snapshots:
                return self._pop_snapshot()
            return self._pop_critical()
