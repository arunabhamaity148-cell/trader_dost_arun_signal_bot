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
        self.tasks: list[asyncio.Task] = []
        self.connectors: list[BasePublicConnector] = []

    async def start(self) -> asyncio.Queue:
        for venue, symbols in self.config.get("watchlist", {}).items():
            connector_cls = CONNECTOR_MAP[venue]
            for symbol in symbols:
                connector = connector_cls(symbol=symbol, latency_monitor=self.latency_monitor, config=self.config.get("connectors", {}).get(venue, {}))
                self.connectors.append(connector)
                self.tasks.append(asyncio.create_task(connector.stream(self.queue), name=f"{venue}-{symbol}"))
        return self.queue

    async def stop(self) -> None:
        await asyncio.gather(*(connector.stop() for connector in self.connectors), return_exceptions=True)
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    @property
    def socket_count(self) -> int:
        return len(self.tasks)

    @property
    def enabled_venues(self) -> list[str]:
        return sorted({connector.venue for connector in self.connectors})

    @property
    def enabled_symbols(self) -> list[str]:
        return [connector.symbol for connector in self.connectors]
