from __future__ import annotations

import abc
import asyncio
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets
from websockets import ConnectionClosed

from trader_dost_arun.core.models import Direction, LiquidationEvent, MarketSnapshot, OrderBookLevel, Trade
from trader_dost_arun.ops.latency import LatencyMonitor

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SharedHttpResources:
    client: httpx.AsyncClient
    semaphore: asyncio.Semaphore
    refs: int = 0


class HeartbeatTimeoutError(TimeoutError):
    pass


def parse_ts(value: int | float | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value > 1_000_000_000_000:
        value = value / 1000
    return datetime.fromtimestamp(value, tz=timezone.utc)


def compute_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.2,
    rng: random.Random | None = None,
) -> float:
    generator = rng or random
    capped = min(max_delay, base_delay * (2 ** max(attempt - 1, 0)))
    jitter_span = capped * max(jitter_ratio, 0.0)
    if jitter_span == 0:
        return capped
    return max(0.0, min(max_delay, capped + generator.uniform(-jitter_span, jitter_span)))


def should_reset_retry_state(uptime_seconds: float, had_messages: bool, stable_window_seconds: float) -> bool:
    return had_messages and uptime_seconds >= stable_window_seconds


class BasePublicConnector(abc.ABC):
    venue: str
    ws_url: str
    rest_url: str
    _shared_http_resources: dict[str, SharedHttpResources] = {}

    def __init__(self, symbol: str, latency_monitor: LatencyMonitor, config: dict[str, Any]):
        self.symbol = symbol
        self.latency_monitor = latency_monitor
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.venue}.{symbol}")
        self._stop = asyncio.Event()
        self._http_resources = self._acquire_shared_http_resources()
        self._rest_client = self._http_resources.client
        self._rest_semaphore = self._http_resources.semaphore
        self._bg_tasks: list[asyncio.Task] = []
        self._cached_mark_price: float | None = None
        self._cached_index_price: float | None = None
        self._cached_funding_rate: float | None = None
        self._cached_open_interest: float | None = None
        self._cached_premium: float | None = None
        self._cached_option_atm_iv: float | None = None
        self._cached_option_put_call_skew: float | None = None
        self._ws = None
        self._closed = False

    def _acquire_shared_http_resources(self) -> SharedHttpResources:
        state = self._shared_http_resources.get(self.venue)
        if state is None:
            timeout_seconds = float(self.config.get("http_timeout_seconds", 10.0))
            limits = httpx.Limits(
                max_connections=max(1, int(self.config.get("http_max_connections", 4))),
                max_keepalive_connections=max(1, int(self.config.get("http_max_keepalive_connections", 2))),
            )
            state = SharedHttpResources(
                client=httpx.AsyncClient(timeout=timeout_seconds, limits=limits, follow_redirects=True),
                semaphore=asyncio.Semaphore(max(1, int(self.config.get("http_max_concurrency", 2)))),
                refs=0,
            )
            self._shared_http_resources[self.venue] = state
        state.refs += 1
        return state

    async def _release_shared_http_resources(self) -> None:
        if self._http_resources is None:
            return
        state = self._http_resources
        self._http_resources = None
        state.refs = max(0, state.refs - 1)
        if state.refs == 0:
            self._shared_http_resources.pop(self.venue, None)
            await state.client.aclose()

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        for task in self._bg_tasks:
            task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
        await self._release_shared_http_resources()

    @abc.abstractmethod
    def subscription_messages(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abc.abstractmethod
    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        raise NotImplementedError

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return []

    def _retry_after_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            return max(0.0, float(retry_after))
        return compute_backoff_delay(
            attempt,
            base_delay=float(self.config.get("http_retry_base_delay_seconds", 1.0)),
            max_delay=float(self.config.get("http_retry_max_delay_seconds", 30.0)),
            jitter_ratio=float(self.config.get("http_retry_jitter_ratio", 0.2)),
        )

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        max_attempts = max(1, int(self.config.get("http_max_attempts", 3)))
        url = f"{self.rest_url}{path}"
        for attempt in range(1, max_attempts + 1):
            try:
                async with self._rest_semaphore:
                    response = await self._rest_client.request(method, url, **kwargs)
                if response.status_code < 400:
                    return response.json()
                if response.status_code in {401, 403, 404}:
                    response.raise_for_status()
                delay = self._retry_after_delay(response, attempt)
                if attempt >= max_attempts:
                    response.raise_for_status()
                self.logger.warning(
                    "rest retry venue=%s symbol=%s path=%s status=%s attempt=%s backoff=%.2fs",
                    self.venue,
                    self.symbol,
                    path,
                    response.status_code,
                    attempt,
                    delay,
                )
                await self._sleep_or_stop(delay)
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                if attempt >= max_attempts:
                    raise
                delay = compute_backoff_delay(
                    attempt,
                    base_delay=float(self.config.get("http_retry_base_delay_seconds", 1.0)),
                    max_delay=float(self.config.get("http_retry_max_delay_seconds", 30.0)),
                    jitter_ratio=float(self.config.get("http_retry_jitter_ratio", 0.2)),
                )
                self.logger.warning(
                    "rest transient error venue=%s symbol=%s path=%s attempt=%s backoff=%.2fs error=%s",
                    self.venue,
                    self.symbol,
                    path,
                    attempt,
                    delay,
                    type(exc).__name__,
                )
                await self._sleep_or_stop(delay)
        raise RuntimeError(f"unreachable request state for {method} {path}")

    async def rest_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request_json("GET", path, params=params)

    async def rest_post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return await self._request_json("POST", path, json=payload)

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
        self.latency_monitor.record(self.venue, snapshot.event_time, symbol=self.symbol)
        await queue.put(snapshot)

    async def _sleep_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return

    def _stable_seed(self, salt: str) -> float:
        raw = f"{self.venue}:{self.symbol}:{salt}".encode("utf-8")
        digest = hashlib.sha1(raw).hexdigest()[:8]
        return int(digest, 16) / 0xFFFFFFFF

    async def stagger_start(self, purpose: str, max_delay_seconds: float = 3.0) -> None:
        if max_delay_seconds <= 0:
            return
        await self._sleep_or_stop(self._stable_seed(purpose) * max_delay_seconds)

    async def _recv_or_probe_liveness(self, websocket: Any, recv_timeout: float, ping_timeout: float) -> str | bytes | None:
        try:
            return await asyncio.wait_for(websocket.recv(), timeout=recv_timeout)
        except asyncio.TimeoutError:
            try:
                pong_waiter = await websocket.ping()
                await asyncio.wait_for(pong_waiter, timeout=ping_timeout)
                self.logger.debug(
                    "quiet feed kept alive venue=%s symbol=%s idle_timeout=%.2fs",
                    self.venue,
                    self.symbol,
                    recv_timeout,
                )
                return None
            except Exception as exc:  # noqa: BLE001
                raise HeartbeatTimeoutError(str(exc)) from exc

    async def stream(self, queue: asyncio.Queue) -> None:
        if not self._bg_tasks:
            self._bg_tasks = self.supplemental_streams(queue)
        attempt = 0
        stable_window = float(self.config.get("stable_connection_reset_seconds", 20.0))
        base_backoff = float(self.config.get("reconnect_base_delay_seconds", 1.0))
        max_backoff = float(self.config.get("reconnect_max_delay_seconds", 30.0))
        jitter_ratio = float(self.config.get("reconnect_jitter_ratio", 0.2))
        recv_timeout = float(self.config.get("recv_timeout_seconds", 30.0))
        ping_timeout = float(self.config.get("idle_ping_timeout_seconds", 10.0))
        await self.stagger_start("ws-connect", max_delay_seconds=float(self.config.get("ws_start_stagger_seconds", 2.0)))
        try:
            while not self._stop.is_set():
                connection_id = uuid.uuid4().hex[:12]
                connected_at = time.monotonic()
                last_message_at: float | None = None
                reason = "disconnect"
                try:
                    async with websockets.connect(self.ws_url, ping_interval=15, ping_timeout=15, max_size=2**24) as websocket:
                        self._ws = websocket
                        self.latency_monitor.connection_open(self.venue, self.symbol, connection_id)
                        for message in self.subscription_messages():
                            await websocket.send(json.dumps(message))
                        self.logger.info("connected venue=%s symbol=%s connection_id=%s", self.venue, self.symbol, connection_id)
                        while not self._stop.is_set():
                            raw = await self._recv_or_probe_liveness(websocket, recv_timeout=recv_timeout, ping_timeout=ping_timeout)
                            if raw is None:
                                continue
                            last_message_at = time.monotonic()
                            self.latency_monitor.record_message(self.venue, self.symbol)
                            payload = json.loads(raw)
                            parsed = self.parse_message(payload)
                            for item in parsed:
                                if isinstance(item, MarketSnapshot):
                                    self._update_cache_from_snapshot(item)
                                self.latency_monitor.record(self.venue, getattr(item, "event_time", datetime.now(timezone.utc)), symbol=self.symbol)
                                await queue.put(item)
                    reason = "socket_closed"
                except asyncio.CancelledError:
                    raise
                except HeartbeatTimeoutError:
                    reason = "heartbeat_timeout"
                except ConnectionClosed as exc:
                    reason = f"connection_closed:{exc.code}"
                except Exception as exc:  # noqa: BLE001
                    reason = type(exc).__name__
                    self.latency_monitor.error(self.venue, self.symbol)
                    self.logger.warning("connector error venue=%s symbol=%s connection_id=%s error=%s", self.venue, self.symbol, connection_id, type(exc).__name__)
                finally:
                    self._ws = None
                if self._stop.is_set():
                    break
                uptime = max(time.monotonic() - connected_at, 0.0)
                had_messages = last_message_at is not None
                last_message_age = None if last_message_at is None else max(time.monotonic() - last_message_at, 0.0)
                if should_reset_retry_state(uptime, had_messages, stable_window):
                    attempt = 1
                    self.latency_monitor.stable_connection(self.venue, self.symbol)
                else:
                    attempt += 1
                backoff = compute_backoff_delay(attempt, base_delay=base_backoff, max_delay=max_backoff, jitter_ratio=jitter_ratio)
                self.latency_monitor.reconnect(self.venue, self.symbol, connection_id, reason, uptime, last_message_age, attempt, backoff)
                self.logger.warning(
                    "reconnect venue=%s symbol=%s connection_id=%s reason=%s uptime=%.2fs last_message_age=%s attempt=%s backoff=%.2fs",
                    self.venue,
                    self.symbol,
                    connection_id,
                    reason,
                    uptime,
                    f"{last_message_age:.2f}s" if last_message_age is not None else "none",
                    attempt,
                    backoff,
                )
                await self._sleep_or_stop(backoff)
        finally:
            await self.stop()

    def _coerce_level(self, level: Any) -> tuple[float, float]:
        if isinstance(level, dict):
            price = level.get("price", level.get("px", level.get("p", 0.0)))
            size = level.get("size", level.get("sz", level.get("q", 0.0)))
            return float(price or 0.0), float(size or 0.0)
        if isinstance(level, (list, tuple)):
            numeric_values: list[float] = []
            for item in level:
                try:
                    numeric_values.append(float(item))
                except (TypeError, ValueError):
                    continue
                if len(numeric_values) == 2:
                    break
            if len(numeric_values) >= 2:
                return numeric_values[0], numeric_values[1]
            return 0.0, 0.0
        return 0.0, 0.0

    def build_snapshot(
        self,
        event_time: datetime,
        bids: list[Any],
        asks: list[Any],
        mark_price: float | None = None,
        index_price: float | None = None,
        funding_rate: float | None = None,
        open_interest: float | None = None,
        premium: float | None = None,
        option_atm_iv: float | None = None,
        option_put_call_skew: float | None = None,
    ) -> MarketSnapshot:
        bid_levels = [OrderBookLevel(price=price, size=size) for price, size in (self._coerce_level(level) for level in bids[:10]) if price or size]
        ask_levels = [OrderBookLevel(price=price, size=size) for price, size in (self._coerce_level(level) for level in asks[:10]) if price or size]
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
