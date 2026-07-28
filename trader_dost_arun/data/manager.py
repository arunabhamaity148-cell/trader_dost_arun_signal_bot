from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from trader_dost_arun.data.base import BasePublicConnector
from trader_dost_arun.data.binance import BinanceConnector
from trader_dost_arun.data.bybit import BybitConnector
from trader_dost_arun.data.deribit import DeribitConnector
from trader_dost_arun.data.grouped import (
    BinanceGroupedConnector,
    BybitGroupedConnector,
    DeribitGroupedConnector,
    GroupedPublicConnector,
    HyperliquidGroupedConnector,
    OkxGroupedConnector,
)
from trader_dost_arun.data.ingress import BoundedMarketQueue
from trader_dost_arun.data.hyperliquid import HyperliquidConnector
from trader_dost_arun.data.okx import OkxConnector
from trader_dost_arun.ops.latency import LatencyMonitor


CONNECTOR_MAP = {
    "binance": BinanceConnector,
    "bybit": BybitConnector,
    "okx": OkxConnector,
    "hyperliquid": HyperliquidConnector,
    "deribit": DeribitConnector,
}

GROUPED_CONNECTOR_MAP = {
    "binance": BinanceGroupedConnector,
    "bybit": BybitGroupedConnector,
    "okx": OkxGroupedConnector,
    "hyperliquid": HyperliquidGroupedConnector,
    "deribit": DeribitGroupedConnector,
}

DEFAULT_MAX_SYMBOLS_PER_CONNECTION = {
    "binance": 5,
    "bybit": 5,
    "okx": 5,
    "hyperliquid": 5,
    "deribit": 20,
}


class ConnectorManager:
    def __init__(self, config: dict[str, Any], latency_monitor: LatencyMonitor):
        self.config = config
        self.latency_monitor = latency_monitor
        queue_maxsize = max(1, int(self.config.get("system", {}).get("market_queue_maxsize", 5000)))
        snapshot_ratio = float(self.config.get("system", {}).get("market_queue_snapshot_capacity_ratio", 0.7))
        self.queue: BoundedMarketQueue = BoundedMarketQueue(maxsize=queue_maxsize, snapshot_capacity_ratio=snapshot_ratio)
        self.tasks: dict[str, asyncio.Task] = {}
        self.connectors: dict[str, BasePublicConnector | GroupedPublicConnector] = {}
        self._topology: dict[str, list[list[str]]] = defaultdict(list)
        self._started = False

    def _feed_key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def _unique_watchlist(self) -> dict[str, list[str]]:
        ordered: dict[str, list[str]] = defaultdict(list)
        seen: set[str] = set()
        for venue, symbols in self.config.get("watchlist", {}).items():
            for symbol in symbols:
                feed_key = self._feed_key(venue, symbol)
                if feed_key in seen:
                    continue
                seen.add(feed_key)
                ordered[venue].append(symbol)
        return ordered

    def _chunk_symbols(self, venue: str, symbols: list[str]) -> list[list[str]]:
        connector_cfg = self.config.get("connectors", {}).get(venue, {})
        max_per_connection = int(connector_cfg.get("max_symbols_per_connection", DEFAULT_MAX_SYMBOLS_PER_CONNECTION.get(venue, 1)))
        max_per_connection = max(1, max_per_connection)
        return [symbols[index : index + max_per_connection] for index in range(0, len(symbols), max_per_connection)]

    def topology(self) -> dict[str, list[list[str]]]:
        return {venue: [list(group) for group in groups] for venue, groups in self._topology.items()}

    async def start(self) -> asyncio.Queue:
        if self._started:
            return self.queue
        for venue, symbols in self._unique_watchlist().items():
            connector_cfg = self.config.get("connectors", {}).get(venue, {})
            grouped_cls = GROUPED_CONNECTOR_MAP.get(venue)
            if grouped_cls is not None:
                for index, group in enumerate(self._chunk_symbols(venue, symbols), start=1):
                    connector = grouped_cls(
                        symbols=group,
                        group_id=str(index),
                        latency_monitor=self.latency_monitor,
                        config=connector_cfg,
                    )
                    connector_key = f"{venue}:group:{index}"
                    self.connectors[connector_key] = connector
                    self._topology[venue].append(list(group))
                    self.tasks[connector_key] = asyncio.create_task(connector.stream(self.queue), name=f"{venue}-group-{index}")
                continue
            connector_cls = CONNECTOR_MAP[venue]
            for symbol in symbols:
                connector = connector_cls(symbol=symbol, latency_monitor=self.latency_monitor, config=connector_cfg)
                feed_key = self._feed_key(venue, symbol)
                self.connectors[feed_key] = connector
                self._topology[venue].append([symbol])
                self.tasks[feed_key] = asyncio.create_task(connector.stream(self.queue), name=f"{venue}-{symbol}")
        self._started = True
        return self.queue

    async def stop(self) -> None:
        await asyncio.gather(*(connector.stop() for connector in self.connectors.values()), return_exceptions=True)
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.connectors.clear()
        self._topology.clear()
        self._started = False

    @property
    def socket_count(self) -> int:
        return len(self.tasks)

    @property
    def enabled_venues(self) -> list[str]:
        return sorted({connector.venue for connector in self.connectors.values()})

    @property
    def enabled_symbols(self) -> list[str]:
        symbols: list[str] = []
        for connector in self.connectors.values():
            if hasattr(connector, "symbols"):
                symbols.extend(list(getattr(connector, "symbols")))
            else:
                symbols.append(connector.symbol)
        return symbols
