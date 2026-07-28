from __future__ import annotations

import abc
import asyncio
import hashlib
import json
import logging
import random
import socket
import time
import uuid
from dataclasses import dataclass, field
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
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refs: int = 0
    last_request_monotonic: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0


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


def is_systemic_disconnect(reason: str) -> bool:
    return reason == "heartbeat_timeout" or reason.startswith("connection_closed:10") or reason in {"socket_closed", "gaierror", "ConnectTimeout", "ReadTimeout", "ConnectError", "NetworkError", "TransportError", "TimeoutError"}


def classify_transport_error(exc: BaseException) -> str:
    if isinstance(exc, socket.gaierror):
        return "gaierror"
    if isinstance(exc, httpx.ConnectTimeout):
        return "ConnectTimeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "ReadTimeout"
    if isinstance(exc, httpx.ConnectError):
        return "ConnectError"
    if isinstance(exc, httpx.TimeoutException):
        return type(exc).__name__ or "TimeoutError"
    if isinstance(exc, httpx.NetworkError):
        return type(exc).__name__ or "NetworkError"
    if isinstance(exc, httpx.TransportError):
        return type(exc).__name__ or "TransportError"
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if isinstance(exc, OSError) and "getaddrinfo failed" in str(exc).lower():
        return "gaierror"
    return type(exc).__name__


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
        self._last_core_event_time: datetime | None = None
        self._last_core_arrival_time: datetime | None = None
        self._last_ws_message_time: datetime | None = None
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

    async def _wait_for_rest_slot(self) -> None:
        min_interval = max(0.0, float(self.config.get("http_min_interval_seconds", 0.0)))
        async with self._http_resources.request_lock:
            now = time.monotonic()
            if self._http_resources.circuit_open_until > now:
                await self._sleep_or_stop(self._http_resources.circuit_open_until - now)
            now = time.monotonic()
            wait = max((self._http_resources.last_request_monotonic + min_interval) - now, 0.0)
            if wait > 0:
                await self._sleep_or_stop(wait)
            self._http_resources.last_request_monotonic = time.monotonic()

    def _mark_rest_success(self) -> None:
        self._http_resources.consecutive_failures = 0
        self._http_resources.circuit_open_until = 0.0

    def _mark_rest_failure(self, attempt: int) -> float:
        self._http_resources.consecutive_failures += 1
        failure_count = self._http_resources.consecutive_failures
        threshold = max(1, int(self.config.get("http_circuit_breaker_failures", 3)))
        if failure_count < threshold:
            return 0.0
        cooldown = compute_backoff_delay(
            failure_count,
            base_delay=float(self.config.get("http_circuit_breaker_base_delay_seconds", 5.0)),
            max_delay=float(self.config.get("http_circuit_breaker_max_delay_seconds", 60.0)),
            jitter_ratio=float(self.config.get("http_retry_jitter_ratio", 0.2)),
        )
        self._http_resources.circuit_open_until = max(self._http_resources.circuit_open_until, time.monotonic() + cooldown)
        return cooldown

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        max_attempts = max(1, int(self.config.get("http_max_attempts", 3)))
        url = f"{self.rest_url}{path}"
        for attempt in range(1, max_attempts + 1):
            try:
                await self._wait_for_rest_slot()
                async with self._rest_semaphore:
                    response = await self._rest_client.request(method, url, **kwargs)
                if response.status_code < 400:
                    self._mark_rest_success()
                    return response.json()
                if response.status_code in {401, 403, 404}:
                    response.raise_for_status()
                delay = self._retry_after_delay(response, attempt)
                circuit_delay = self._mark_rest_failure(attempt)
                delay = max(delay, circuit_delay)
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
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError, TimeoutError, OSError) as exc:
                error_type = classify_transport_error(exc)
                circuit_delay = self._mark_rest_failure(attempt)
                systemic = self.latency_monitor.record_transport_failure(self.venue, self.symbol, error_type)
                if attempt >= max_attempts:
                    raise
                delay = compute_backoff_delay(
                    attempt,
                    base_delay=float(self.config.get("http_retry_base_delay_seconds", 1.0)),
                    max_delay=float(self.config.get("http_retry_max_delay_seconds", 30.0)),
                    jitter_ratio=float(self.config.get("http_retry_jitter_ratio", 0.2)),
                )
                if systemic:
                    delay = max(delay, float(self.config.get("network_degraded_rest_backoff_seconds", 5.0)))
                delay = max(delay, circuit_delay)
                self.logger.warning(
                    "rest transient error venue=%s symbol=%s path=%s attempt=%s backoff=%.2fs error=%s network_degraded=%s",
                    self.venue,
                    self.symbol,
                    path,
                    attempt,
                    delay,
                    error_type,
                    systemic,
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
        if snapshot.core_event_time is not None:
            self._last_core_event_time = snapshot.core_event_time
        if snapshot.core_arrival_time is not None:
            self._last_core_arrival_time = snapshot.core_arrival_time
        if snapshot.update_class == "core":
            self._last_ws_message_time = snapshot.arrival_time

    async def emit_snapshot(self, queue: asyncio.Queue, **kwargs: Any) -> None:
        snapshot = self.build_snapshot(datetime.now(timezone.utc), [], [], is_core_update=False, **kwargs)
        if snapshot.core_event_time is not None:
            self.latency_monitor.record(self.venue, snapshot.core_event_time, symbol=self.symbol)
        await queue.put(snapshot)

    async def _sleep_or_stop(self, delay: float) -> None:
        if delay <= 0:
            return
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
        degraded_base_backoff = float(self.config.get("network_degraded_base_delay_seconds", 5.0))
        degraded_max_backoff = float(self.config.get("network_degraded_max_delay_seconds", 120.0))
        await self.stagger_start("ws-connect", max_delay_seconds=float(self.config.get("ws_start_stagger_seconds", 2.0)))
        try:
            while not self._stop.is_set():
                if self.latency_monitor.is_network_degraded():
                    degraded_delay = compute_backoff_delay(
                        max(attempt, 1),
                        base_delay=degraded_base_backoff,
                        max_delay=degraded_max_backoff,
                        jitter_ratio=jitter_ratio,
                    )
                    await self._sleep_or_stop(degraded_delay)
                    if self._stop.is_set():
                        break
                connection_id = uuid.uuid4().hex[:12]
                connected_at = time.monotonic()
                last_message_at: float | None = None
                reason = "disconnect"
                try:
                    async with websockets.connect(self.ws_url, ping_interval=None, ping_timeout=None, close_timeout=5, max_size=2**24, max_queue=32) as websocket:
                        self._ws = websocket
                        is_owner = self.latency_monitor.connection_open(self.venue, self.symbol, connection_id)
                        if not is_owner:
                            self.logger.warning("duplicate connection ownership venue=%s symbol=%s connection_id=%s", self.venue, self.symbol, connection_id)
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
                                    event_reference = item.core_event_time or item.event_time
                                else:
                                    event_reference = getattr(item, "event_time", datetime.now(timezone.utc))
                                self.latency_monitor.record(self.venue, event_reference, symbol=self.symbol)
                                await queue.put(item)
                    reason = "socket_closed"
                except asyncio.CancelledError:
                    raise
                except HeartbeatTimeoutError:
                    reason = "heartbeat_timeout"
                    self.latency_monitor.error(self.venue, self.symbol)
                    self.latency_monitor.record_transport_failure(self.venue, self.symbol, reason)
                except ConnectionClosed as exc:
                    close_code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(websocket, "close_code", None) or 1006
                    reason = f"connection_closed:{close_code}"
                    if is_systemic_disconnect(reason):
                        self.latency_monitor.record_transport_failure(self.venue, self.symbol, reason)
                except Exception as exc:  # noqa: BLE001
                    reason = classify_transport_error(exc)
                    systemic = self.latency_monitor.record_transport_failure(self.venue, self.symbol, reason)
                    self.logger.warning(
                        "connector error venue=%s symbol=%s connection_id=%s error=%s network_degraded=%s",
                        self.venue,
                        self.symbol,
                        connection_id,
                        reason,
                        systemic,
                    )
                finally:
                    self.latency_monitor.connection_closed(self.venue, self.symbol, connection_id)
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
                if self.latency_monitor.is_network_degraded():
                    backoff = max(
                        backoff,
                        compute_backoff_delay(
                            attempt,
                            base_delay=degraded_base_backoff,
                            max_delay=degraded_max_backoff,
                            jitter_ratio=jitter_ratio,
                        ),
                    )
                self.latency_monitor.reconnect(self.venue, self.symbol, connection_id, reason, uptime, last_message_age, attempt, backoff)
                self.logger.warning(
                    "reconnect venue=%s symbol=%s connection_id=%s reason=%s uptime=%.2fs last_message_age=%s attempt=%s backoff=%.2fs network_state=%s",
                    self.venue,
                    self.symbol,
                    connection_id,
                    reason,
                    uptime,
                    f"{last_message_age:.2f}s" if last_message_age is not None else "none",
                    attempt,
                    backoff,
                    self.latency_monitor.network_status()["state"],
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
        is_core_update: bool = True,
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
        arrival_time = datetime.now(timezone.utc)
        core_event_time = event_time if is_core_update else self._last_core_event_time
        core_arrival_time = arrival_time if is_core_update else self._last_core_arrival_time
        enrichment_event_time = None if is_core_update else event_time
        enrichment_arrival_time = None if is_core_update else arrival_time
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
            arrival_time=arrival_time,
            core_event_time=core_event_time,
            core_arrival_time=core_arrival_time,
            enrichment_event_time=enrichment_event_time,
            enrichment_arrival_time=enrichment_arrival_time,
            update_class="core" if is_core_update else "enrichment",
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
