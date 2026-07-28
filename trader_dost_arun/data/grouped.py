from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import websockets
from websockets import ConnectionClosed

from trader_dost_arun.core.models import Direction, LiquidationEvent, MarketSnapshot, OrderBookLevel, Trade
from trader_dost_arun.data.base import (
    BasePublicConnector,
    HeartbeatTimeoutError,
    classify_transport_error,
    compute_backoff_delay,
    is_systemic_disconnect,
    parse_ts,
    should_reset_retry_state,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SymbolCacheState:
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    premium: float | None = None
    option_atm_iv: float | None = None
    option_put_call_skew: float | None = None
    last_core_event_time: datetime | None = None
    last_core_arrival_time: datetime | None = None
    last_ws_message_time: datetime | None = None


class GroupedPublicConnector(BasePublicConnector):
    """Single websocket owner for a bounded group of symbols within a venue."""

    venue = "grouped"

    def __init__(self, symbols: list[str], group_id: str, latency_monitor, config: dict[str, Any]):
        self.symbols = list(dict.fromkeys(symbols))
        if not self.symbols:
            raise ValueError("GroupedPublicConnector requires at least one symbol")
        self.group_id = str(group_id)
        self.group_label = f"group-{self.group_id}"
        self._symbol_states = {symbol: SymbolCacheState() for symbol in self.symbols}
        super().__init__(symbol=self.group_label, latency_monitor=latency_monitor, config=config)
        self.logger = logging.getLogger(f"{__name__}.{self.venue}.{self.group_label}")
        self._symbol_alias_map = self._build_symbol_alias_map(self.symbols)

    def _build_symbol_alias_map(self, symbols: list[str]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for symbol in symbols:
            raw = symbol.lower()
            aliases[raw] = symbol
            aliases[raw.replace("-", "")] = symbol
            aliases[raw.replace("/", "")] = symbol
        return aliases

    def _canonical_symbol(self, raw_symbol: str | None) -> str | None:
        if not raw_symbol:
            return None
        lowered = str(raw_symbol).lower()
        return self._symbol_alias_map.get(lowered) or self._symbol_alias_map.get(lowered.replace("-", "")) or self._symbol_alias_map.get(lowered.replace("/", ""))

    def _state(self, symbol: str) -> SymbolCacheState:
        if symbol not in self._symbol_states:
            self._symbol_states[symbol] = SymbolCacheState()
        return self._symbol_states[symbol]

    def _merge_symbol_cache(self, symbol: str, value: float | None, attr: str) -> float | None:
        state = self._state(symbol)
        cached = getattr(state, attr)
        return value if value is not None else cached

    def _update_symbol_cache_from_snapshot(self, snapshot: MarketSnapshot) -> None:
        state = self._state(snapshot.symbol)
        if snapshot.mark_price is not None:
            state.mark_price = snapshot.mark_price
        if snapshot.index_price is not None:
            state.index_price = snapshot.index_price
        if snapshot.funding_rate is not None:
            state.funding_rate = snapshot.funding_rate
        if snapshot.open_interest is not None:
            state.open_interest = snapshot.open_interest
        if snapshot.premium is not None:
            state.premium = snapshot.premium
        if snapshot.option_atm_iv is not None:
            state.option_atm_iv = snapshot.option_atm_iv
        if snapshot.option_put_call_skew is not None:
            state.option_put_call_skew = snapshot.option_put_call_skew
        if snapshot.core_event_time is not None:
            state.last_core_event_time = snapshot.core_event_time
        if snapshot.core_arrival_time is not None:
            state.last_core_arrival_time = snapshot.core_arrival_time
        if snapshot.update_class == "core":
            state.last_ws_message_time = snapshot.arrival_time

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

    def build_group_snapshot(
        self,
        symbol: str,
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
        state = self._state(symbol)
        bid_levels = [OrderBookLevel(price=price, size=size) for price, size in (self._coerce_level(level) for level in bids[:10]) if price or size]
        ask_levels = [OrderBookLevel(price=price, size=size) for price, size in (self._coerce_level(level) for level in asks[:10]) if price or size]
        spread = ask_levels[0].price - bid_levels[0].price if bid_levels and ask_levels else 0.0
        merged_mark = self._merge_symbol_cache(symbol, mark_price, "mark_price")
        merged_index = self._merge_symbol_cache(symbol, index_price, "index_price")
        merged_funding = self._merge_symbol_cache(symbol, funding_rate, "funding_rate")
        merged_oi = self._merge_symbol_cache(symbol, open_interest, "open_interest")
        merged_premium = premium if premium is not None else state.premium
        if merged_premium is None and merged_mark is not None and merged_index is not None:
            merged_premium = merged_mark - merged_index
        arrival_time = datetime.now(timezone.utc)
        core_event_time = event_time if is_core_update else state.last_core_event_time
        core_arrival_time = arrival_time if is_core_update else state.last_core_arrival_time
        enrichment_event_time = None if is_core_update else event_time
        enrichment_arrival_time = None if is_core_update else arrival_time
        snapshot = MarketSnapshot(
            venue=self.venue,
            symbol=symbol,
            event_time=event_time,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
            mark_price=merged_mark,
            index_price=merged_index,
            funding_rate=merged_funding,
            open_interest=merged_oi,
            premium=merged_premium,
            spread=spread,
            option_atm_iv=self._merge_symbol_cache(symbol, option_atm_iv, "option_atm_iv"),
            option_put_call_skew=self._merge_symbol_cache(symbol, option_put_call_skew, "option_put_call_skew"),
            arrival_time=arrival_time,
            core_event_time=core_event_time,
            core_arrival_time=core_arrival_time,
            enrichment_event_time=enrichment_event_time,
            enrichment_arrival_time=enrichment_arrival_time,
            update_class="core" if is_core_update else "enrichment",
        )
        self._update_symbol_cache_from_snapshot(snapshot)
        return snapshot

    def build_group_trade(self, symbol: str, price: float, size: float, side: str, event_time: datetime) -> Trade:
        return Trade(
            venue=self.venue,
            symbol=symbol,
            price=float(price),
            size=float(size),
            side=Direction.SHORT if side.lower() in {"sell", "s", "short", "-1"} else Direction.LONG,
            event_time=event_time,
        )

    def build_group_liquidation(self, symbol: str, price: float, size: float, side: str, event_time: datetime) -> LiquidationEvent:
        return LiquidationEvent(
            venue=self.venue,
            symbol=symbol,
            side=Direction.SHORT if side.lower() in {"sell", "s", "short", "-1"} else Direction.LONG,
            price=float(price),
            size=float(size),
            event_time=event_time,
        )

    async def emit_group_snapshot(self, queue: asyncio.Queue, symbol: str, **kwargs: Any) -> None:
        snapshot = self.build_group_snapshot(symbol, datetime.now(timezone.utc), [], [], is_core_update=False, **kwargs)
        if snapshot.core_event_time is not None:
            self.latency_monitor.record(self.venue, snapshot.core_event_time, symbol=symbol)
        await queue.put(snapshot)

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
                            self.logger.warning("duplicate connection ownership event=duplicate_connection venue=%s connection_id=%s group=%s", self.venue, connection_id, self.group_label)
                        for message in self.subscription_messages():
                            await websocket.send(json.dumps(message))
                        self.logger.info(
                            "event=ws_connected venue=%s group=%s connection_id=%s symbols=%s",
                            self.venue,
                            self.group_label,
                            connection_id,
                            len(self.symbols),
                        )
                        while not self._stop.is_set():
                            raw = await self._recv_or_probe_liveness(websocket, recv_timeout=recv_timeout, ping_timeout=ping_timeout)
                            if raw is None:
                                continue
                            last_message_at = time.monotonic()
                            payload = json.loads(raw)
                            parsed = self.parse_message(payload)
                            touched_symbols = {item.symbol for item in parsed}
                            for touched_symbol in touched_symbols:
                                self.latency_monitor.record_message(self.venue, touched_symbol)
                            for item in parsed:
                                if isinstance(item, MarketSnapshot):
                                    self._update_symbol_cache_from_snapshot(item)
                                    event_reference = item.core_event_time or item.event_time
                                else:
                                    event_reference = getattr(item, "event_time", datetime.now(timezone.utc))
                                self.latency_monitor.record(self.venue, event_reference, symbol=item.symbol)
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
                        "event=connector_error venue=%s group=%s connection_id=%s error=%s network_degraded=%s",
                        self.venue,
                        self.group_label,
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
                    "event=ws_reconnect venue=%s group=%s connection_id=%s reason=%s uptime=%.2fs last_message_age=%s attempt=%s backoff=%.2fs network_state=%s",
                    self.venue,
                    self.group_label,
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


class BinanceGroupedConnector(GroupedPublicConnector):
    venue = "binance"
    ws_url = "wss://fstream.binance.com/stream"
    rest_url = "https://fapi.binance.com"

    def subscription_messages(self) -> list[dict[str, Any]]:
        streams: list[str] = []
        for symbol in self.symbols:
            s = symbol.lower().replace("/", "")
            streams.extend([f"{s}@depth20@100ms", f"{s}@trade", f"{s}@markPrice@1s", f"{s}@forceOrder"])
        return [{"method": "SUBSCRIBE", "params": streams, "id": 1}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_open_interest_group(queue), name=f"{self.venue}-{self.group_label}-oi")]

    async def _poll_open_interest_group(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("open-interest-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            for symbol in self.symbols:
                if self._stop.is_set():
                    break
                try:
                    payload = await self.rest_json("/fapi/v1/openInterest", params={"symbol": symbol})
                    value = payload.get("openInterest")
                    if value is not None:
                        await self.emit_group_snapshot(queue, symbol, open_interest=float(value))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("event=rest_enrichment_failed venue=%s group=%s symbol=%s kind=open_interest error=%s", self.venue, self.group_label, symbol, type(exc).__name__)
            await self._sleep_or_stop(interval)

    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        data = payload.get("data", payload)
        stream = payload.get("stream", "")
        symbol = self._canonical_symbol(stream.split("@", 1)[0])
        if symbol is None:
            return []
        if "depth" in stream and data.get("b") and data.get("a"):
            return [self.build_group_snapshot(symbol, parse_ts(data.get("E")), data["b"], data["a"])]
        if "trade" in stream and data.get("p"):
            return [self.build_group_trade(symbol, data["p"], data["q"], "sell" if data.get("m") else "buy", parse_ts(data.get("T")))]
        if "markPrice" in stream:
            snap = self.build_group_snapshot(symbol, parse_ts(data.get("E")), [], [], float(data.get("p", 0.0)), float(data.get("i", 0.0)), float(data.get("r", 0.0)))
            snap.premium = (snap.mark_price or 0.0) - (snap.index_price or 0.0)
            return [snap]
        if "forceOrder" in stream and data.get("o"):
            order = data["o"]
            return [self.build_group_liquidation(symbol, order.get("p", 0.0), order.get("q", 0.0), order.get("S", "buy"), parse_ts(order.get("T")))]
        return []


class BybitGroupedConnector(GroupedPublicConnector):
    venue = "bybit"
    ws_url = "wss://stream.bybit.com/v5/public/linear"
    rest_url = "https://api.bybit.com"

    def subscription_messages(self) -> list[dict[str, Any]]:
        args: list[str] = []
        for symbol in self.symbols:
            args.extend([f"orderbook.50.{symbol}", f"publicTrade.{symbol}", f"tickers.{symbol}"])
        return [{"op": "subscribe", "args": args}]

    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        topic = payload.get("topic", "")
        symbol = self._canonical_symbol(topic.rsplit(".", 1)[-1])
        if symbol is None:
            return []
        data = payload.get("data", {})
        if topic.startswith("orderbook") and data:
            return [self.build_group_snapshot(symbol, parse_ts(payload.get("ts")), data.get("b", []), data.get("a", []))]
        if topic.startswith("publicTrade"):
            return [self.build_group_trade(symbol, item.get("p", 0.0), item.get("v", 0.0), item.get("S", "buy"), parse_ts(item.get("T"))) for item in data]
        if topic.startswith("tickers") and data:
            snap = self.build_group_snapshot(symbol, parse_ts(payload.get("ts")), [], [], float(data.get("markPrice", 0.0)), float(data.get("indexPrice", 0.0)), float(data.get("fundingRate", 0.0)), float(data.get("openInterest", 0.0)))
            snap.premium = (snap.mark_price or 0.0) - (snap.index_price or 0.0)
            return [snap]
        return []


class OkxGroupedConnector(GroupedPublicConnector):
    venue = "okx"
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    rest_url = "https://www.okx.com"

    def subscription_messages(self) -> list[dict[str, Any]]:
        args: list[dict[str, str]] = []
        for symbol in self.symbols:
            args.extend(
                [
                    {"channel": "books5", "instId": symbol},
                    {"channel": "trades", "instId": symbol},
                    {"channel": "mark-price", "instId": symbol},
                    {"channel": "funding-rate", "instId": symbol},
                ]
            )
        return [{"op": "subscribe", "args": args}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_open_interest_group(queue), name=f"{self.venue}-{self.group_label}-oi")]

    async def _poll_open_interest_group(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("open-interest-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            for symbol in self.symbols:
                if self._stop.is_set():
                    break
                try:
                    payload = await self.rest_json("/api/v5/public/open-interest", params={"instType": "SWAP", "instId": symbol})
                    rows = payload.get("data", [])
                    if rows:
                        value = rows[0].get("oi") or rows[0].get("openInterest")
                        if value is not None:
                            await self.emit_group_snapshot(queue, symbol, open_interest=float(value))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("event=rest_enrichment_failed venue=%s group=%s symbol=%s kind=open_interest error=%s", self.venue, self.group_label, symbol, type(exc).__name__)
            await self._sleep_or_stop(interval)

    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        arg = payload.get("arg", {})
        symbol = self._canonical_symbol(arg.get("instId"))
        if symbol is None:
            return []
        channel = arg.get("channel", "")
        data = payload.get("data", [])
        if channel == "books5" and data:
            book = data[0]
            return [self.build_group_snapshot(symbol, parse_ts(int(book.get("ts", 0))), book.get("bids", []), book.get("asks", []))]
        if channel == "trades":
            return [self.build_group_trade(symbol, item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(int(item.get("ts", 0)))) for item in data]
        if channel in {"mark-price", "funding-rate"} and data:
            item = data[0]
            snap = self.build_group_snapshot(symbol, parse_ts(int(item.get("ts", 0))), [], [], float(item.get("markPx", 0.0)), float(item.get("indexPx", 0.0)), float(item.get("fundingRate", 0.0)))
            snap.premium = (snap.mark_price or 0.0) - (snap.index_price or 0.0)
            return [snap]
        return []


class HyperliquidGroupedConnector(GroupedPublicConnector):
    venue = "hyperliquid"
    ws_url = "wss://api.hyperliquid.xyz/ws"
    rest_url = "https://api.hyperliquid.xyz"

    def _build_symbol_alias_map(self, symbols: list[str]) -> dict[str, str]:
        aliases = super()._build_symbol_alias_map(symbols)
        for symbol in symbols:
            aliases[symbol.split("-")[0].lower()] = symbol
        return aliases

    def subscription_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"method": "subscribe", "subscription": {"type": "allMids"}}]
        for symbol in self.symbols:
            coin = symbol.split("-")[0]
            messages.extend(
                [
                    {"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}},
                    {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}},
                    {"method": "subscribe", "subscription": {"type": "liquidations", "coin": coin}},
                ]
            )
        return messages

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_asset_context_group(queue), name=f"{self.venue}-{self.group_label}-assetctx")]

    async def _poll_asset_context_group(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("asset-context-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            try:
                payload = await self.rest_post_json("/info", {"type": "metaAndAssetCtxs"})
                ctx_map = self._parse_asset_context_map(payload)
                for symbol, ctx in ctx_map.items():
                    await self.emit_group_snapshot(
                        queue,
                        symbol,
                        mark_price=ctx.get("mark_price"),
                        index_price=ctx.get("index_price"),
                        funding_rate=ctx.get("funding_rate"),
                        open_interest=ctx.get("open_interest"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=rest_enrichment_failed venue=%s group=%s kind=asset_context error=%s", self.venue, self.group_label, type(exc).__name__)
            await self._sleep_or_stop(interval)

    def _parse_asset_context_map(self, payload: list[Any] | dict[str, Any]) -> dict[str, dict[str, float]]:
        if not isinstance(payload, list) or len(payload) < 2:
            return {}
        universe = payload[0].get("universe", []) if isinstance(payload[0], dict) else []
        contexts = payload[1] if isinstance(payload[1], list) else []
        out: dict[str, dict[str, float]] = {}
        for index, item in enumerate(universe):
            name = item.get("name") or item.get("coin")
            symbol = self._canonical_symbol(name)
            if symbol is None or index >= len(contexts):
                continue
            ctx = contexts[index]
            mark = float(ctx.get("markPx") or 0.0)
            oracle = float(ctx.get("oraclePx") or mark)
            out[symbol] = {
                "mark_price": mark,
                "index_price": oracle,
                "funding_rate": float(ctx.get("funding") or 0.0),
                "open_interest": float(ctx.get("openInterest") or 0.0),
            }
        return out

    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        channel = payload.get("channel", "")
        data = payload.get("data", {})
        if channel == "l2Book" and data:
            symbol = self._canonical_symbol(data.get("coin") or data.get("symbol") or payload.get("coin"))
            if symbol is None:
                return []
            levels = data.get("levels", [[], []])
            bids = levels[0] if len(levels) > 0 else []
            asks = levels[1] if len(levels) > 1 else []
            return [self.build_group_snapshot(symbol, parse_ts(data.get("time")), bids, asks)]
        if channel == "trades":
            out: list[Trade] = []
            rows = data if isinstance(data, list) else []
            for item in rows:
                symbol = self._canonical_symbol(item.get("coin") or item.get("symbol"))
                if symbol is None:
                    continue
                out.append(self.build_group_trade(symbol, item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(item.get("time"))))
            return out
        if channel == "allMids" and data:
            mids = data.get("mids", {}) if isinstance(data, dict) else {}
            out: list[MarketSnapshot] = []
            for symbol in self.symbols:
                coin = symbol.split("-")[0]
                if coin not in mids:
                    continue
                px = float(mids.get(coin, 0.0))
                out.append(self.build_group_snapshot(symbol, parse_ts(payload.get("time")), [], [], px, px))
            return out
        if channel == "liquidations":
            out: list[LiquidationEvent] = []
            rows = data if isinstance(data, list) else []
            for item in rows:
                symbol = self._canonical_symbol(item.get("coin") or item.get("symbol"))
                if symbol is None:
                    continue
                out.append(self.build_group_liquidation(symbol, item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(item.get("time"))))
            return out
        return []


class DeribitGroupedConnector(GroupedPublicConnector):
    venue = "deribit"
    ws_url = "wss://www.deribit.com/ws/api/v2"
    rest_url = "https://www.deribit.com/api/v2"

    def _build_symbol_alias_map(self, symbols: list[str]) -> dict[str, str]:
        aliases = super()._build_symbol_alias_map(symbols)
        for symbol in symbols:
            aliases[symbol.split("-")[0].lower()] = symbol
        return aliases

    def subscription_messages(self) -> list[dict[str, Any]]:
        channels: list[str] = []
        for symbol in self.symbols:
            channels.extend([f"book.{symbol}.100ms", f"trades.{symbol}.100ms", f"ticker.{symbol}.100ms"])
        return [{"jsonrpc": "2.0", "id": 42, "method": "public/subscribe", "params": {"channels": channels}}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_option_metrics_group(queue), name=f"{self.venue}-{self.group_label}-options")]

    async def _poll_option_metrics_group(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("options_poll_seconds", 30))
        await self.stagger_start("option-metrics-poll", max_delay_seconds=min(float(interval), 5.0))
        symbols_by_currency: dict[str, list[str]] = {}
        for symbol in self.symbols:
            symbols_by_currency.setdefault(symbol.split("-")[0], []).append(symbol)
        while not self._stop.is_set():
            for currency, symbols in symbols_by_currency.items():
                if self._stop.is_set():
                    break
                try:
                    payload = await self.rest_json("/public/get_book_summary_by_currency", params={"currency": currency, "kind": "option"})
                    metrics = self._compute_option_metrics(payload.get("result", []))
                    if metrics:
                        for symbol in symbols:
                            await self.emit_group_snapshot(queue, symbol, option_atm_iv=metrics["atm_iv"], option_put_call_skew=metrics["put_call_skew"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("event=rest_enrichment_failed venue=%s group=%s currency=%s kind=options error=%s", self.venue, self.group_label, currency, type(exc).__name__)
            await self._sleep_or_stop(interval)

    def _compute_option_metrics(self, rows: list[dict[str, Any]]) -> dict[str, float] | None:
        from collections import defaultdict
        from datetime import datetime

        best_by_expiry: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
        for row in rows:
            instrument = row.get("instrument_name", "")
            parts = instrument.split("-")
            if len(parts) < 4:
                continue
            expiry = parts[1]
            strike = float(parts[2])
            option_type = parts[3]
            underlying = float(row.get("underlying_price") or 0.0)
            mark_iv = row.get("mark_iv")
            if not underlying or mark_iv is None:
                continue
            distance = abs(strike - underlying)
            existing = best_by_expiry[expiry].get(option_type)
            if existing is None or distance < existing["distance"]:
                best_by_expiry[expiry][option_type] = {"distance": distance, "mark_iv": float(mark_iv)}
        if not best_by_expiry:
            return None
        expiry = min(best_by_expiry, key=lambda key: datetime.strptime(key, "%d%b%y"))
        selected = best_by_expiry[expiry]
        call_iv = selected.get("C", {}).get("mark_iv")
        put_iv = selected.get("P", {}).get("mark_iv")
        ivs = [iv for iv in [call_iv, put_iv] if iv is not None]
        if not ivs:
            return None
        atm_iv = sum(ivs) / len(ivs)
        skew = (put_iv or atm_iv) - (call_iv or atm_iv)
        return {"atm_iv": atm_iv, "put_call_skew": skew}

    def parse_message(self, payload: dict[str, Any]) -> list[MarketSnapshot | Trade | LiquidationEvent]:
        params = payload.get("params", {})
        channel = params.get("channel", "")
        data = params.get("data", {})
        parts = channel.split(".")
        symbol = self._canonical_symbol(parts[1] if len(parts) >= 2 else None)
        if symbol is None:
            return []
        if channel.startswith("book"):
            return [self.build_group_snapshot(symbol, parse_ts(data.get("timestamp")), data.get("bids", []), data.get("asks", []), data.get("mark_price"), data.get("index_price"), data.get("current_funding", 0.0), data.get("open_interest", 0.0), (data.get("mark_price", 0.0) - data.get("index_price", 0.0)))]
        if channel.startswith("trades"):
            return [self.build_group_trade(symbol, item.get("price", 0.0), item.get("amount", 0.0), item.get("direction", "buy"), parse_ts(item.get("timestamp"))) for item in data]
        if channel.startswith("ticker") and data:
            snap = self.build_group_snapshot(symbol, parse_ts(data.get("timestamp")), [], [], data.get("mark_price", 0.0), data.get("index_price", 0.0), data.get("current_funding", 0.0), data.get("open_interest", 0.0), data.get("mark_price", 0.0) - data.get("index_price", 0.0))
            return [snap]
        return []
