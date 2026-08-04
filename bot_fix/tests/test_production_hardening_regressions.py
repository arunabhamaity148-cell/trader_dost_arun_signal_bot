from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from websockets import ConnectionClosedError

from app import TradingApplication, _current_rss_mb
from trader_dost_arun.core.config import load_settings
from trader_dost_arun.core.models import Direction, LiquidationEvent, MarketSnapshot, OrderBookLevel, Trade, utc_now
from trader_dost_arun.data.base import BasePublicConnector
from trader_dost_arun.data.external import ExternalDataClient
from trader_dost_arun.data.ingress import BoundedMarketQueue
from trader_dost_arun.ops.latency import LatencyMonitor

ROOT = Path(__file__).resolve().parents[1]


class NoopService:
    client = None

    async def start(self):
        return None

    async def close(self):
        return None

    async def stop(self):
        return None

    def current_context(self):
        return None

    def cache_sizes(self):
        return {}


def build_snapshot(venue: str, symbol: str, *, mark_price: float = 100.0) -> MarketSnapshot:
    ts = utc_now() - timedelta(milliseconds=100)
    return MarketSnapshot(
        venue=venue,
        symbol=symbol,
        event_time=ts,
        arrival_time=ts,
        core_event_time=ts,
        core_arrival_time=ts,
        bid_levels=[OrderBookLevel(mark_price - 1, 1)],
        ask_levels=[OrderBookLevel(mark_price + 1, 1)],
        mark_price=mark_price,
        index_price=mark_price,
        funding_rate=0.0,
        open_interest=1.0,
        premium=0.0,
        spread=2.0,
    )


@pytest.mark.asyncio
async def test_bounded_market_queue_coalesces_latest_snapshot_state():
    queue = BoundedMarketQueue(maxsize=4, snapshot_capacity_ratio=0.75)
    await queue.put(build_snapshot("binance", "BTCUSDT", mark_price=100.0))
    await queue.put(build_snapshot("binance", "BTCUSDT", mark_price=101.0))
    await queue.put(build_snapshot("okx", "BTC-USDT-SWAP", mark_price=99.0))
    assert queue.qsize() == 2
    counters = queue.snapshot()
    assert counters["coalesced_snapshots"] == 1
    seen = []
    while not queue.empty():
        seen.append(await queue.get())
    btc = next(item for item in seen if item.symbol == "BTCUSDT")
    assert btc.mark_price == 101.0


@pytest.mark.asyncio
async def test_bounded_market_queue_preserves_liquidations_under_pressure():
    queue = BoundedMarketQueue(maxsize=2, snapshot_capacity_ratio=0.5)
    await queue.put(build_snapshot("binance", "BTCUSDT"))
    await queue.put(
        Trade(
            venue="binance",
            symbol="BTCUSDT",
            price=100.0,
            size=1.0,
            side=Direction.LONG,
            event_time=utc_now(),
        )
    )
    await queue.put(
        LiquidationEvent(
            venue="binance",
            symbol="BTCUSDT",
            side=Direction.SHORT,
            price=99.0,
            size=2.0,
            event_time=utc_now(),
        )
    )
    counters = queue.snapshot()
    assert counters["dropped_snapshots"] == 1
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert any(isinstance(item, LiquidationEvent) for item in events)


def test_rss_telemetry_reports_real_memory_usage_on_linux():
    rss_mb = _current_rss_mb()
    assert rss_mb > 0.0


def test_connection_closed_1006_counts_as_systemic_failure():
    monitor = LatencyMonitor(systemic_min_failures=2, systemic_min_venues=2, recovery_successes=1)
    assert monitor.record_transport_failure("binance", "BTCUSDT", "connection_closed:1006") is False
    assert monitor.record_transport_failure("okx", "BTC-USDT-SWAP", "connection_closed:1006") is True
    assert monitor.is_network_degraded() is True


@pytest.mark.asyncio
async def test_external_data_start_isolates_bootstrap_failures(monkeypatch):
    client = ExternalDataClient(refresh_seconds=1)

    async def boom():
        raise httpx.ConnectError("down")

    monkeypatch.setattr(client, "refresh_once", boom)
    await client.start()
    try:
        assert client._task is not None
    finally:
        await client.close()


class ReconnectingConnector(BasePublicConnector):
    venue = "dummy"
    ws_url = "wss://example.invalid/ws"
    rest_url = "https://example.invalid"

    def __init__(self, symbol, latency_monitor, config):
        super().__init__(symbol, latency_monitor, config)
        self.supplemental_calls = 0

    def subscription_messages(self):
        return []

    def parse_message(self, payload):
        del payload
        return []

    def supplemental_streams(self, queue):
        del queue
        self.supplemental_calls += 1
        return []


class FailingWebSocket:
    async def recv(self):
        raise ConnectionClosedError(None, None)

    async def ping(self):
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        return fut

    async def send(self, payload):
        del payload

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_reconnect_loop_does_not_duplicate_supplemental_workers(monkeypatch):
    connector = ReconnectingConnector(
        "BTCUSDT",
        LatencyMonitor(systemic_min_failures=99, systemic_min_venues=99),
        {
            "reconnect_base_delay_seconds": 0.01,
            "reconnect_max_delay_seconds": 0.01,
            "recv_timeout_seconds": 0.01,
            "idle_ping_timeout_seconds": 0.01,
            "ws_start_stagger_seconds": 0.0,
        },
    )

    @asynccontextmanager
    async def fake_connect(*_args, **_kwargs):
        yield FailingWebSocket()

    monkeypatch.setattr("trader_dost_arun.data.base.websockets.connect", fake_connect)
    task = asyncio.create_task(connector.stream(BoundedMarketQueue(maxsize=8)))
    await asyncio.sleep(0.05)
    await connector.stop()
    await asyncio.gather(task, return_exceptions=True)
    assert connector.supplemental_calls == 1


@pytest.mark.asyncio
async def test_runtime_snapshot_exposes_queue_overload_counters():
    settings = load_settings(ROOT)
    settings.config["watchlist"] = {}
    settings.config["ops"]["health_port"] = 18088
    app = TradingApplication(ROOT, settings=settings)

    class ManagerStub:
        enabled_venues = ["binance"]
        enabled_symbols = ["BTCUSDT"]
        socket_count = 0

        def topology(self):
            return {"binance": [["BTCUSDT"]]}

        async def start(self):
            queue = BoundedMarketQueue(maxsize=2, snapshot_capacity_ratio=0.5)
            await queue.put(build_snapshot("binance", "BTCUSDT", mark_price=100.0))
            await queue.put(build_snapshot("binance", "BTCUSDT", mark_price=101.0))
            return queue

        async def stop(self):
            return None

    app.manager = ManagerStub()
    app.external_client = NoopService()
    app.news_guard = NoopService()
    app.bot = NoopService()
    await app.start()
    try:
        snapshot = app.runtime_snapshot()
        assert "queue_overload" in snapshot
        assert snapshot["queue_overload"]["coalesced_snapshots"] >= 1
    finally:
        await app.stop()
