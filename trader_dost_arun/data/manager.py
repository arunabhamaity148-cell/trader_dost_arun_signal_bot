from __future__ import annotations

import asyncio
from typing import Any

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

    async def start(self) -> asyncio.Queue:
        for venue, symbols in self.config.get("watchlist", {}).items():
            connector_cls = CONNECTOR_MAP[venue]
            for symbol in symbols:
                connector = connector_cls(symbol=symbol, latency_monitor=self.latency_monitor, config=self.config.get("connectors", {}).get(venue, {}))
                self.tasks.append(asyncio.create_task(connector.stream(self.queue), name=f"{venue}-{symbol}"))
        return self.queue

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
