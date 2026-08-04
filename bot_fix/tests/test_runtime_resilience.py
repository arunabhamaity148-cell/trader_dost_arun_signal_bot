import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app import TradingApplication
from trader_dost_arun.core.config import load_settings
from trader_dost_arun.data.base import BasePublicConnector, HeartbeatTimeoutError
from trader_dost_arun.newsguard.sources import RSSNewsSource
from trader_dost_arun.ops.latency import LatencyMonitor
from trader_dost_arun.ops.logging_utils import SafeStreamHandler, SecretRedactionFilter

ROOT = Path(__file__).resolve().parents[1]


class DummyConnector(BasePublicConnector):
    venue = "dummy"
    ws_url = "wss://example.invalid/ws"
    rest_url = "https://example.invalid"

    def subscription_messages(self) -> list[dict]:
        return []

    def parse_message(self, payload: dict):
        return []


class QuietWebSocket:
    async def recv(self):
        await asyncio.sleep(0.05)
        return json.dumps({"kind": "late-message"})

    async def ping(self):
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future


class DeadWebSocket:
    async def recv(self):
        await asyncio.sleep(0.05)
        return json.dumps({"kind": "late-message"})

    async def ping(self):
        return asyncio.get_running_loop().create_future()


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


class NoopAlerts:
    consecutive_send_failures = 0
    last_send_error = None

    async def health_alert(self, *_args, **_kwargs):
        return None

    async def signal_alert(self, *_args, **_kwargs):
        return "sent"


class FakeManager:
    def __init__(self) -> None:
        self.enabled_venues = ["binance"]
        self.enabled_symbols = ["BTCUSDT"]
        self.socket_count = 1
        self._queue = asyncio.Queue()

    async def start(self) -> asyncio.Queue:
        return self._queue

    async def stop(self) -> None:
        return None


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def test_reconnect_event_runtime_snapshot_and_endpoints_survive_reconnect():
    async def runner() -> None:
        settings = load_settings(ROOT)
        settings.config["watchlist"] = {}
        settings.config["ops"]["health_port"] = 18082
        settings.config["ops"]["health_refresh_seconds"] = 0.05
        app = TradingApplication(ROOT, settings=settings)
        app.manager = FakeManager()
        app.external_client = NoopService()
        app.news_guard = NoopService()
        app.bot = NoopService()
        app.alerts = NoopAlerts()
        await app.start()
        try:
            app.latency.record("binance", datetime.now(timezone.utc), symbol="BTCUSDT")
            app.latency.reconnect(
                venue="binance",
                symbol="BTCUSDT",
                connection_id="abc123",
                reason="heartbeat_timeout",
                uptime=31.5,
                last_message_age=30.1,
                attempt=2,
                backoff=1.25,
            )
            await asyncio.sleep(0.2)
            snapshot = app.runtime_snapshot()
            assert snapshot["recent_reconnects"][0]["reason"] == "heartbeat_timeout"
            assert snapshot["recent_reconnects"][0]["timestamp"].endswith("+00:00")
            health = await _fetch_text("http://127.0.0.1:18082/health")
            metrics = await _fetch_text("http://127.0.0.1:18082/metrics")
            assert '"venues": {"binance"' in health or '"venues": {"binance":' in health
            assert "venue_health_score" in metrics
            assert app.stats.unexpected_exceptions == []
        finally:
            await app.stop()

    asyncio.run(runner())


@pytest.mark.asyncio
async def test_quiet_feed_is_not_treated_as_dead_connection():
    connector = DummyConnector("BTCUSDT", LatencyMonitor(), {})
    try:
        raw = await connector._recv_or_probe_liveness(QuietWebSocket(), recv_timeout=0.01, ping_timeout=0.01)
        assert raw is None
    finally:
        await connector.stop()


@pytest.mark.asyncio
async def test_dead_connection_without_pong_raises_heartbeat_timeout():
    connector = DummyConnector("BTCUSDT", LatencyMonitor(), {})
    try:
        with pytest.raises(HeartbeatTimeoutError):
            await connector._recv_or_probe_liveness(DeadWebSocket(), recv_timeout=0.01, ping_timeout=0.01)
    finally:
        await connector.stop()


def test_secret_redaction_filter_masks_fake_telegram_token_in_logs():
    fake_token = "123456:FAKE_SECRET_TOKEN_FOR_TEST"
    stream = io.StringIO()
    handler = SafeStreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("secret-redaction-test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.warning(
        "telegram send failed url=https://api.telegram.org/bot%s/sendMessage?token=%s authorization=Bearer %s",
        fake_token,
        fake_token,
        fake_token,
    )
    output = stream.getvalue()
    assert fake_token not in output
    assert "<REDACTED" in output


def test_newsguard_malformed_rss_is_deduplicated(caplog):
    class FakeResponse:
        headers = {"content-type": "text/html"}
        text = "<html><body>not rss</body></html>"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    async def runner() -> tuple[list, list]:
        source = RSSNewsSource("broken-feed", FakeClient(), "https://example.com/rss")
        first = await source.fetch()
        second = await source.fetch()
        return first, second

    with caplog.at_level(logging.WARNING):
        first, second = asyncio.run(runner())
    assert first == []
    assert second == []
    messages = [record.getMessage() for record in caplog.records if "news source broken-feed failed" in record.getMessage()]
    assert len(messages) == 1
