import asyncio
import io
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app import TradingApplication
from trader_dost_arun.core.config import load_settings
from trader_dost_arun.core.models import MarketSnapshot, OrderBookLevel, utc_now
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.base import BasePublicConnector, SharedHttpResources
from trader_dost_arun.newsguard.sources import RSSNewsSource
from trader_dost_arun.ops.latency import LatencyMonitor
from trader_dost_arun.ops.logging_utils import SanitizingFormatter

ROOT = Path(__file__).resolve().parents[1]


class DummyConnector(BasePublicConnector):
    venue = "dummy"
    ws_url = "wss://example.invalid/ws"
    rest_url = "https://example.invalid"

    def subscription_messages(self):
        return []

    def parse_message(self, payload):
        if payload.get("kind") == "book":
            return [self.build_snapshot(utc_now(), [[100, 1]], [[101, 1]])]
        return []


class FakeManager:
    def __init__(self):
        self.enabled_venues = ["binance"]
        self.enabled_symbols = ["BTCUSDT"]
        self.socket_count = 1
        self._queue = asyncio.Queue()
        self.stop_calls = 0

    async def start(self):
        return self._queue

    async def stop(self):
        self.stop_calls += 1


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


class RaisingAlerts:
    consecutive_send_failures = 0
    last_send_error = None

    async def health_alert(self, *_args, **_kwargs):
        raise RuntimeError("alert transport down")

    async def signal_alert(self, *_args, **_kwargs):
        return "sent"


class ClosingClient:
    def __init__(self):
        self.closed = False
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.fail_times = 0

    async def request(self, method, url, **kwargs):
        del method, url, kwargs
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            if self.fail_times > 0:
                self.fail_times -= 1
                raise httpx.ConnectTimeout("timeout")
            return httpx.Response(200, json={"ok": True})
        finally:
            self.active -= 1

    async def aclose(self):
        self.closed = True


class CooldownClient:
    def __init__(self):
        self.calls = 0

    async def get(self, *_args, **_kwargs):
        self.calls += 1
        raise httpx.ReadTimeout("no rss")


class EmptyRSSClient:
    def __init__(self):
        self.calls = 0

    async def get(self, *_args, **_kwargs):
        self.calls += 1

        class Response:
            headers = {"content-type": "application/rss+xml"}
            text = "<rss><channel><item><title>hello BTC</title><description>body</description><link>https://example.com</link></item></channel></rss>"

            def raise_for_status(self):
                return None

        return Response()


class FakeWebSocket:
    def __init__(self):
        self.closed = False
        self.recv_calls = 0
        self.sent = []

    async def recv(self):
        self.recv_calls += 1
        if self.recv_calls == 1:
            return '{"kind":"book"}'
        await asyncio.sleep(0.05)
        raise TimeoutError("boom")

    async def ping(self):
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        return fut

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


class FakeWebSocketContext:
    def __init__(self, websocket, calls):
        self.websocket = websocket
        self.calls = calls

    async def __aenter__(self):
        self.calls.append("enter")
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        self.calls.append("exit")
        return False


class FailingHealthScorer:
    def __init__(self):
        self.calls = 0

    def score(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError("broken health scorer")


class QueueCaptureHandler(logging.StreamHandler):
    def __init__(self):
        self.stream = io.StringIO()
        super().__init__(self.stream)
        self.setFormatter(SanitizingFormatter("%(levelname)s %(message)s"))



def snapshot(venue: str, symbol: str, age_seconds: float, *, update_class: str = "core") -> MarketSnapshot:
    ts = utc_now() - timedelta(seconds=age_seconds)
    return MarketSnapshot(
        venue=venue,
        symbol=symbol,
        event_time=ts,
        arrival_time=ts,
        core_event_time=ts if update_class == "core" else utc_now() - timedelta(seconds=10),
        core_arrival_time=ts if update_class == "core" else utc_now() - timedelta(seconds=10),
        enrichment_event_time=ts if update_class == "enrichment" else None,
        enrichment_arrival_time=ts if update_class == "enrichment" else None,
        update_class=update_class,
        bid_levels=[OrderBookLevel(99, 1)],
        ask_levels=[OrderBookLevel(101, 1)],
        mark_price=100,
        index_price=100,
        funding_rate=0.0,
        open_interest=1.0,
        premium=0.0,
        spread=2.0,
    )


@pytest.mark.asyncio
async def test_connection_ownership_detects_duplicate_owner():
    monitor = LatencyMonitor()
    assert monitor.connection_open("binance", "BTCUSDT", "conn-1") is True
    assert monitor.connection_open("binance", "BTCUSDT", "conn-2") is False
    assert monitor.runtime_snapshot()["duplicate_connection_attempts"] == 1


@pytest.mark.asyncio
async def test_systemic_network_degraded_and_recovery():
    monitor = LatencyMonitor(systemic_min_failures=2, systemic_min_venues=2, recovery_successes=2)
    assert monitor.record_transport_failure("binance", "BTCUSDT", "gaierror") is False
    assert monitor.record_transport_failure("okx", "BTC-USDT-SWAP", "ConnectTimeout") is True
    assert monitor.is_network_degraded() is True
    monitor.record_connection_success("binance", "BTCUSDT")
    assert monitor.is_network_degraded() is True
    monitor.record_connection_success("okx", "BTC-USDT-SWAP")
    assert monitor.is_network_degraded() is False


@pytest.mark.asyncio
async def test_rest_retry_budget_is_bounded():
    connector = DummyConnector("BTCUSDT", LatencyMonitor(), {"http_max_attempts": 3, "http_retry_base_delay_seconds": 0.0, "http_retry_max_delay_seconds": 0.0})
    client = ClosingClient()
    client.fail_times = 3
    connector._rest_client = client
    connector._http_resources.client = client
    with pytest.raises(httpx.ConnectTimeout):
        await connector.rest_json("/ping")
    assert client.calls == 3
    await connector.stop()


@pytest.mark.asyncio
async def test_rest_concurrency_is_bounded_by_shared_semaphore():
    config = {"http_max_concurrency": 2, "http_min_interval_seconds": 0.0}
    c1 = DummyConnector("BTCUSDT", LatencyMonitor(), config)
    c2 = DummyConnector("ETHUSDT", LatencyMonitor(), config)
    client = ClosingClient()
    c1._rest_client = client
    c2._rest_client = client
    c1._http_resources.client = client
    c2._http_resources.client = client
    await asyncio.gather(*(connector.rest_json("/ping") for connector in [c1, c1, c2, c2]))
    assert client.max_active <= 2
    await c1.stop()
    await c2.stop()


def test_optional_enrichment_does_not_refresh_core_freshness():
    state = MarketStateStore()
    state.add_snapshot(snapshot("binance", "BTCUSDT", 10.0, update_class="core"))
    enrichment = snapshot("binance", "BTCUSDT", 0.1, update_class="enrichment")
    state.add_snapshot(enrichment)
    freshness = state.freshness("binance", "BTCUSDT", max_age_seconds=2.0, min_sources=1)
    assert freshness.own_age_seconds is not None and freshness.own_age_seconds > 2.0
    assert freshness.own_enrichment_age_seconds is not None and freshness.own_enrichment_age_seconds < 1.0
    assert freshness.freshness_rejection_reason == "stale_core_market_data"


def test_fresh_core_with_stale_optional_enrichment_still_passes_quorum():
    state = MarketStateStore()
    fresh = snapshot("binance", "BTCUSDT", 0.2, update_class="core")
    fresh.enrichment_event_time = utc_now() - timedelta(seconds=30)
    fresh.enrichment_arrival_time = utc_now() - timedelta(seconds=30)
    state.add_snapshot(fresh)
    state.add_snapshot(snapshot("okx", "BTC-USDT-SWAP", 0.3, update_class="core"))
    status = state.freshness("binance", "BTCUSDT", max_age_seconds=2.0, min_sources=2)
    assert status.quorum_met is True
    assert status.own_age_seconds is not None and status.own_age_seconds < 2.0
    assert status.own_enrichment_age_seconds is not None and status.own_enrichment_age_seconds > 2.0


@pytest.mark.asyncio
async def test_shutdown_prevents_reconnect_and_closes_websocket(monkeypatch):
    monitor = LatencyMonitor(systemic_min_failures=99, systemic_min_venues=99)
    connector = DummyConnector("BTCUSDT", monitor, {"reconnect_base_delay_seconds": 0.01, "reconnect_max_delay_seconds": 0.01, "recv_timeout_seconds": 0.01, "idle_ping_timeout_seconds": 0.01, "ws_start_stagger_seconds": 0.0})
    ws = FakeWebSocket()
    calls = []

    @asynccontextmanager
    async def fake_connect(*_args, **_kwargs):
        try:
            yield ws
        finally:
            await ws.close()

    monkeypatch.setattr("trader_dost_arun.data.base.websockets.connect", fake_connect)
    queue = asyncio.Queue()
    task = asyncio.create_task(connector.stream(queue))
    await asyncio.sleep(0.03)
    await connector.stop()
    await asyncio.gather(task, return_exceptions=True)
    assert ws.closed is True
    snapshot = monitor.runtime_snapshot()
    assert snapshot["active_connections"] == {}


@pytest.mark.asyncio
async def test_connector_stop_closes_http_client_once():
    connector = DummyConnector("BTCUSDT", LatencyMonitor(), {})
    client = ClosingClient()
    connector._rest_client = client
    connector._http_resources = SharedHttpResources(client=client, semaphore=asyncio.Semaphore(1), refs=1)
    await connector.stop()
    assert client.closed is True


def test_log_line_integrity_and_traceback_redaction():
    handler = QueueCaptureHandler()
    logger = logging.getLogger("single-line-redaction-test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        raise RuntimeError("https://user:secret@example.com boom token=123456:FAKE_SECRET_TOKEN_FOR_TEST")
    except RuntimeError:
        logger.exception("failure authorization=Bearer secret-token chat_id=12345")
    output = handler.stream.getvalue().strip()
    assert "secret" not in output
    assert "FAKE_SECRET_TOKEN_FOR_TEST" not in output
    assert "<REDACTED" in output
    assert "\\n" in output
    assert "\n" not in output


@pytest.mark.asyncio
async def test_news_source_cooldown_backoff_and_isolation():
    source = RSSNewsSource("broken", CooldownClient(), "https://example.com/rss")
    assert await source.fetch() == []
    assert source.health.consecutive_failures == 1
    skipped_before = source.health.skipped_due_to_cooldown
    assert await source.fetch() == []
    assert source.health.skipped_due_to_cooldown == skipped_before + 1
    healthy_source = RSSNewsSource("healthy", EmptyRSSClient(), "https://example.com/rss")
    rows = await healthy_source.fetch()
    assert len(rows) == 1
    assert healthy_source.health.last_success_at is not None


@pytest.mark.asyncio
async def test_health_loop_survives_component_failure():
    settings = load_settings(ROOT)
    settings.config["watchlist"] = {}
    settings.config["ops"]["health_port"] = 18084
    settings.config["ops"]["health_refresh_seconds"] = 0.05
    app = TradingApplication(ROOT, settings=settings)
    app.manager = FakeManager()
    app.external_client = NoopService()
    app.news_guard = NoopService()
    app.bot = NoopService()
    app.alerts = RaisingAlerts()
    app.health = FailingHealthScorer()
    await app.start()
    try:
        await asyncio.sleep(0.15)
        assert any(task.get_name() == "health-loop" and not task.done() for task in app._background_tasks)
        assert app.stats.unexpected_exceptions
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_run_forever_cancellation_exits_cleanly():
    settings = load_settings(ROOT)
    settings.config["watchlist"] = {}
    settings.config["ops"]["health_port"] = 18085
    settings.config["ops"]["health_refresh_seconds"] = 0.05
    app = TradingApplication(ROOT, settings=settings)
    app.manager = FakeManager()
    app.external_client = NoopService()
    app.news_guard = NoopService()
    app.bot = NoopService()
    app.alerts = RaisingAlerts()
    task = asyncio.create_task(app.run_forever())
    await asyncio.sleep(0.1)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert result == [None]
    assert app.queue is None
