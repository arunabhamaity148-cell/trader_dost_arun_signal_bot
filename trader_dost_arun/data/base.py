from __future__ import annotations

import abc
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets

from trader_dost_arun.core.models import Direction, LiquidationEvent, MarketSnapshot, OrderBookLevel, Trade
from trader_dost_arun.ops.latency import LatencyMonitor

LOGGER = logging.getLogger(__name__)


def parse_ts(value: int | float | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value > 1_000_000_000_000:
        value = value / 1000
    return datetime.fromtimestamp(value, tz=timezone.utc)


class BasePublicConnector(abc.ABC):
    venue: str
    ws_url: str
    rest_url: str

    def __init__(self, symbol: str, latency_monitor: LatencyMonitor, config: dict[str, Any]):
        self.symbol = symbol
        self.latency_monitor = latency_monitor
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.venue}.{symbol}")
        self._stop = asyncio.Event()
        self._rest_client = httpx.AsyncClient(timeout=10)
        self._bg_tasks: list[asyncio.Task] = []
        self._cached_mark_price: float | None = None
        self._cached_index_price: float | None = None
        self._cached_funding_rate: float | None = None
        self._cached_open_interest: float | None = None
        self._cached_premium: float | None = None
        self._cached_option_atm_iv: float | None = None
        self._cached_option_put_call_skew: float | None = None

    async def stop(self) -> None:
        self._stop.set()
        for task in self._bg_tasks:
            task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        await self._rest_client.aclose()

    @abc.abstractmethod
    def subscription_messages(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abc.abstractmethod
    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        raise NotImplementedError

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return []

    async def rest_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._rest_client.get(f"{self.rest_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    async def rest_post_json(self, path: str, payload: dict[str, Any]) -> Any:
        response = await self._rest_client.post(f"{self.rest_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()

    def _merge_cache(self, value: float | None, cached_attr: str) -> float | None:
        cached = getattr(self, cached_attr)
        return value if value is not None else cached

    def _update_cache_from_snapshot(self, snapshot: MarketSnapshot) -> None:
        if snapshot.mark_price is not None:
            self._cached_mark_price = snapshot.mark_price
        if snapshot.index_price is not None:
            self._cached_index_price = snapshot.index_price
        if snapshot.funding_rate is not None:
            self._cached_funding_rate = snapshot.funding_rate
        if snapshot.open_interest is not None:
            self._cached_open_interest = snapshot.open_interest
        if snapshot.premium is not None:
            self._cached_premium = snapshot.premium
        if snapshot.option_atm_iv is not None:
            self._cached_option_atm_iv = snapshot.option_atm_iv
        if snapshot.option_put_call_skew is not None:
            self._cached_option_put_call_skew = snapshot.option_put_call_skew

    async def emit_snapshot(self, queue: asyncio.Queue, **kwargs: Any) -> None:
        snapshot = self.build_snapshot(datetime.now(timezone.utc), [], [], **kwargs)
        self.latency_monitor.record(self.venue, snapshot.event_time)
        await queue.put(snapshot)

    async def stream(self, queue: asyncio.Queue) -> None:
        if not self._bg_tasks:
            self._bg_tasks = self.supplemental_streams(queue)
        backoff = 1.0
        try:
            while not self._stop.is_set():
                try:
                    async with websockets.connect(self.ws_url, ping_interval=15, ping_timeout=15, max_size=2**24) as websocket:
                        for message in self.subscription_messages():
                            await websocket.send(json.dumps(message))
                        self.logger.info("connected")
                        backoff = 1.0
                        while not self._stop.is_set():
                            raw = await asyncio.wait_for(websocket.recv(), timeout=30)
                            payload = json.loads(raw)
                            parsed = self.parse_message(payload)
                            for item in parsed:
                                if isinstance(item, MarketSnapshot):
                                    self._update_cache_from_snapshot(item)
                                self.latency_monitor.record(self.venue, getattr(item, "event_time", datetime.now(timezone.utc)))
                                await queue.put(item)
                except asyncio.TimeoutError:
                    self.latency_monitor.reconnect(self.venue)
                    self.logger.warning("timeout, reconnecting")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.latency_monitor.error(self.venue)
                    self.latency_monitor.reconnect(self.venue)
                    self.logger.exception("connector error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        finally:
            for task in self._bg_tasks:
                task.cancel()
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
            await self._rest_client.aclose()

    def build_snapshot(
        self,
        event_time: datetime,
        bids: list[list[float]],
        asks: list[list[float]],
        mark_price: float | None = None,
        index_price: float | None = None,
        funding_rate: float | None = None,
        open_interest: float | None = None,
        premium: float | None = None,
        option_atm_iv: float | None = None,
        option_put_call_skew: float | None = None,
    ) -> MarketSnapshot:
        bid_levels = [OrderBookLevel(price=float(price), size=float(size)) for price, size in bids[:10]]
        ask_levels = [OrderBookLevel(price=float(price), size=float(size)) for price, size in asks[:10]]
        spread = ask_levels[0].price - bid_levels[0].price if bid_levels and ask_levels else 0.0
        merged_mark = self._merge_cache(mark_price, "_cached_mark_price")
        merged_index = self._merge_cache(index_price, "_cached_index_price")
        merged_funding = self._merge_cache(funding_rate, "_cached_funding_rate")
        merged_oi = self._merge_cache(open_interest, "_cached_open_interest")
        merged_premium = premium if premium is not None else self._cached_premium
        if merged_premium is None and merged_mark is not None and merged_index is not None:
            merged_premium = merged_mark - merged_index
        snapshot = MarketSnapshot(
            venue=self.venue,
            symbol=self.symbol,
            event_time=event_time,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
            mark_price=merged_mark,
            index_price=merged_index,
            funding_rate=merged_funding,
            open_interest=merged_oi,
            premium=merged_premium,
            spread=spread,
            option_atm_iv=self._merge_cache(option_atm_iv, "_cached_option_atm_iv"),
            option_put_call_skew=self._merge_cache(option_put_call_skew, "_cached_option_put_call_skew"),
        )
        self._update_cache_from_snapshot(snapshot)
        return snapshot

    def build_trade(self, price: float, size: float, side: str, event_time: datetime) -> Trade:
        return Trade(
            venue=self.venue,
            symbol=self.symbol,
            price=float(price),
            size=float(size),
            side=Direction.SHORT if side.lower() in {"sell", "s", "short", "-1"} else Direction.LONG,
            event_time=event_time,
        )

    def build_liquidation(self, price: float, size: float, side: str, event_time: datetime) -> LiquidationEvent:
        return LiquidationEvent(
            venue=self.venue,
            symbol=self.symbol,
            side=Direction.SHORT if side.lower() in {"sell", "s", "short", "-1"} else Direction.LONG,
            price=float(price),
            size=float(size),
            event_time=event_time,
        )
