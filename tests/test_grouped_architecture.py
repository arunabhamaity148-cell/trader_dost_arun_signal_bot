import asyncio
import json
import logging
import queue
from pathlib import Path

import pytest

from app import TradingApplication
from trader_dost_arun.core.config import load_settings
from trader_dost_arun.data.grouped import BinanceGroupedConnector, HyperliquidGroupedConnector
from trader_dost_arun.data.manager import ConnectorManager
from trader_dost_arun.newsguard.embeddings import SemanticTextEmbedder
from trader_dost_arun.ops.latency import LatencyMonitor
from trader_dost_arun.ops.logging_utils import BoundedQueueHandler

ROOT = Path(__file__).resolve().parents[1]


class DummyGroupedConnector:
    venue = "dummy"

    def __init__(self, symbols, group_id, latency_monitor, config):
        del latency_monitor, config
        self.symbols = list(symbols)
        self.symbol = f"group-{group_id}"
        self._stop = asyncio.Event()

    async def stream(self, queue_):
        del queue_
        await self._stop.wait()

    async def stop(self):
        self._stop.set()


@pytest.mark.asyncio
async def test_connector_manager_groups_watchlist_and_prevents_duplicate_start(monkeypatch):
    from trader_dost_arun.data import manager as manager_module

    monkeypatch.setitem(manager_module.GROUPED_CONNECTOR_MAP, "binance", DummyGroupedConnector)
    config = {
        "system": {"market_queue_maxsize": 123},
        "watchlist": {"binance": [f"SYM{i}" for i in range(10)]},
        "connectors": {"binance": {"max_symbols_per_connection": 5}},
    }
    manager = ConnectorManager(config, LatencyMonitor())
    queue_1 = await manager.start()
    queue_2 = await manager.start()
    try:
        assert queue_1 is queue_2
        assert manager.queue.maxsize == 123
        assert manager.socket_count == 2
        assert manager.topology() == {"binance": [[f"SYM{i}" for i in range(5)], [f"SYM{i}" for i in range(5, 10)]]}
        assert manager.enabled_symbols == [f"SYM{i}" for i in range(10)]
    finally:
        await manager.stop()


def test_default_topology_is_bounded_to_expected_group_counts():
    settings = load_settings(ROOT)
    manager = ConnectorManager(settings.config, LatencyMonitor())
    topology = manager._unique_watchlist()
    assert len(manager._chunk_symbols("binance", topology["binance"])) == 2
    assert len(manager._chunk_symbols("bybit", topology["bybit"])) == 2
    assert len(manager._chunk_symbols("okx", topology["okx"])) == 2
    assert len(manager._chunk_symbols("hyperliquid", topology["hyperliquid"])) == 2
    assert len(manager._chunk_symbols("deribit", topology["deribit"])) == 1


def test_binance_grouped_connector_routes_messages_to_correct_symbol():
    connector = BinanceGroupedConnector(["BTCUSDT", "ETHUSDT"], "1", LatencyMonitor(), {})
    payload = {
        "stream": "ethusdt@trade",
        "data": {"p": "123.4", "q": "0.5", "m": True, "T": 1720000000000},
    }
    parsed = connector.parse_message(payload)
    assert len(parsed) == 1
    assert parsed[0].symbol == "ETHUSDT"


def test_hyperliquid_grouped_connector_all_mids_emits_per_symbol_snapshots():
    connector = HyperliquidGroupedConnector(["BTC-PERP", "ETH-PERP"], "1", LatencyMonitor(), {})
    payload = {"channel": "allMids", "time": 1720000000000, "data": {"mids": {"BTC": "100.0", "ETH": "200.0"}}}
    parsed = connector.parse_message(payload)
    assert {item.symbol for item in parsed} == {"BTC-PERP", "ETH-PERP"}
    assert {item.mark_price for item in parsed} == {100.0, 200.0}


def test_bounded_queue_handler_drops_oldest_without_growing_memory():
    q = queue.Queue(maxsize=1)
    handler = BoundedQueueHandler(q)
    logger = logging.getLogger("bounded-queue-handler-test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("first")
    logger.info("second")
    assert q.qsize() == 1
    record = q.get_nowait()
    assert record.getMessage() == "second"


def test_sentence_transformer_progress_bar_is_disabled(monkeypatch):
    calls = []

    class FakeModel:
        def encode(self, texts, normalize_embeddings, show_progress_bar):
            calls.append({
                "texts": list(texts),
                "normalize_embeddings": normalize_embeddings,
                "show_progress_bar": show_progress_bar,
            })
            return [[1.0, 0.0], [1.0, 0.0]]

    class FakeFactory:
        def __init__(self, model_name):
            self.model_name = model_name

        def encode(self, texts, normalize_embeddings, show_progress_bar):
            return FakeModel().encode(texts, normalize_embeddings, show_progress_bar)

    monkeypatch.setattr("trader_dost_arun.newsguard.embeddings.SentenceTransformer", FakeFactory)
    embedder = SemanticTextEmbedder()
    assert embedder.similarity("btc", "bitcoin") == pytest.approx(1.0)
    assert calls[0]["show_progress_bar"] is False
    assert calls[0]["normalize_embeddings"] is True


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


@pytest.mark.asyncio
async def test_runtime_snapshot_exposes_topology_and_bounded_queue_metrics():
    settings = load_settings(ROOT)
    settings.config["watchlist"] = {}
    settings.config["ops"]["health_port"] = 18086
    app = TradingApplication(ROOT, settings=settings)
    class ManagerStub:
        enabled_venues = ["binance"]
        enabled_symbols = ["BTCUSDT"]
        socket_count = 2

        def topology(self):
            return {"binance": [["BTCUSDT", "ETHUSDT"]]}

        async def start(self):
            return asyncio.Queue(maxsize=77)

        async def stop(self):
            return None

    app.manager = ManagerStub()
    app.external_client = NoopService()
    app.news_guard = NoopService()
    app.bot = NoopService()
    await app.start()
    try:
        snapshot = app.runtime_snapshot()
        assert snapshot["queue_capacity"] == 77
        assert snapshot["topology"]["binance"][0] == ["BTCUSDT", "ETHUSDT"]
    finally:
        await app.stop()
