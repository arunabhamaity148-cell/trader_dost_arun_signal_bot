from __future__ import annotations

import asyncio
from typing import Any

from trader_dost_arun.data.base import BasePublicConnector
from trader_dost_arun.data.binance import BinanceConnector
from trader_dost_arun.data.bybit import BybitConnector
from trader_dost_arun.data.deribit import DeribitConnector
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


class ConnectorManager:
    def __init__(self, config: dict[str, Any], latency_monitor: LatencyMonitor):
        self.config = config
        self.latency_monitor = latency_monitor
        self.queue: asyncio.Queue = asyncio.Queue()
        self.tasks: dict[str, asyncio.Task] = {}
        self.connectors: dict[str, BasePublicConnector] = {}
        self._started = False

    def _feed_key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def _unique_watchlist(self) -> list[tuple[str, str]]:
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for venue, symbols in self.config.get("watchlist", {}).items():
            for symbol in symbols:
                feed_key = self._feed_key(venue, symbol)
                if feed_key in seen:
                    continue
                seen.add(feed_key)
                ordered.append((venue, symbol))
        return ordered

    async def start(self) -> asyncio.Queue:
        if self._started:
            return self.queue
        for venue, symbol in self._unique_watchlist():
            connector_cls = CONNECTOR_MAP[venue]
            connector = connector_cls(
                symbol=symbol,
                latency_monitor=self.latency_monitor,
                config=self.config.get("connectors", {}).get(venue, {}),
            )
            feed_key = self._feed_key(venue, symbol)
            self.connectors[feed_key] = connector
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
        self._started = False

    @property
    def socket_count(self) -> int:
        return len(self.tasks)

    @property
    def enabled_venues(self) -> list[str]:
        return sorted({connector.venue for connector in self.connectors.values()})

    @property
    def enabled_symbols(self) -> list[str]:
        return [connector.symbol for connector in self.connectors.values()]
