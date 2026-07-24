from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from trader_dost_arun.core.config import load_settings
from trader_dost_arun.core.models import LiquidationEvent, MarketSnapshot, Trade
from trader_dost_arun.core.persistence import PositionStore
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalDataClient
from trader_dost_arun.data.manager import ConnectorManager
from trader_dost_arun.features.calculations import compute_features
from trader_dost_arun.newsguard.guard import NewsGuard
from trader_dost_arun.ops.alerts import TelegramAlerter
from trader_dost_arun.ops.health import OpsHttpServer, HealthScorer, LATENCY_HIST, SIGNAL_COUNTER, VETO_COUNTER
from trader_dost_arun.ops.latency import LatencyMonitor
from trader_dost_arun.ops.logging_utils import configure_logging
from trader_dost_arun.ops.telegram_bot import TelegramAdminBot
from trader_dost_arun.signals.engine import SignalEngine

LOGGER = logging.getLogger(__name__)


async def main() -> None:
    project_root = Path(__file__).resolve().parent
    configure_logging(project_root)
    settings = load_settings(project_root)
    state = MarketStateStore(maxlen=settings.config["system"]["history_size"])
    latency = LatencyMonitor()
    health = HealthScorer()
    alerts = TelegramAlerter(settings.telegram_token, settings.telegram_chat_id, settings.config.get("telegram", {}).get("counter_db", "./data/signal_counter.sqlite3"))
    external_client = ExternalDataClient(refresh_seconds=settings.config.get("external", {}).get("refresh_seconds", 180))
    news_cfg = settings.config.setdefault("news_guard", {})
    news_cfg.setdefault("fred_api_key", os.getenv("FRED_API_KEY", ""))
    news_cfg.setdefault("whale_monitor", {})
    if "api_key" not in news_cfg["whale_monitor"]:
        news_cfg["whale_monitor"]["api_key"] = os.getenv("ETHERSCAN_API_KEY", "")
    news_guard = NewsGuard(settings.config, external_client.client)
    position_store = PositionStore(settings.config.get("positions", {}).get("db_path", "./data/positions.sqlite3"))
    signal_engine = SignalEngine(settings.config, news_guard=news_guard, position_store=position_store)
    manager = ConnectorManager(settings.config, latency)
    queue = await manager.start()
    http_server = OpsHttpServer(port=int(settings.config.get("ops", {}).get("health_port", 8080)))
    bot = TelegramAdminBot(settings.telegram_token, os.getenv("TELEGRAM_ADMIN_CHAT_ID", settings.config.get("telegram", {}).get("admin_chat_id", "")), position_store=position_store)
    await http_server.start()
    await external_client.start()
    await news_guard.start()
    await bot.start()
    try:
        while True:
            item = await queue.get()
            if isinstance(item, MarketSnapshot):
                state.add_snapshot(item)
            elif isinstance(item, Trade):
                state.add_trade(item)
            elif isinstance(item, LiquidationEvent):
                state.add_liquidation(item)
            venue = item.venue
            symbol = item.symbol
            await signal_engine.update_open_positions(venue, symbol, state)
            view = state.view(venue, symbol)
            if len(view.snapshots) < settings.config["system"]["min_snapshots_before_signals"]:
                continue
            peers = state.peer_views(symbol)
            feature_map = compute_features(view, peers)
            peer_features = {peer_venue: compute_features(peer_view, peers) for peer_venue, peer_view in peers.items() if peer_view.snapshots}
            external = external_client.current_context()
            signals = await signal_engine.evaluate(venue, symbol, feature_map, state, peer_features, external)
            for signal in signals:
                if signal.direction.value == "flat" or signal.suppressed_reason:
                    if signal.suppressed_reason and VETO_COUNTER is not None:
                        VETO_COUNTER.labels(reason=signal.suppressed_reason).inc()
                    LOGGER.info("signal suppressed %s %s %s", signal.symbol, signal.strategy_name, signal.suppressed_reason)
                    continue
                if SIGNAL_COUNTER is not None:
                    SIGNAL_COUNTER.inc()
                LOGGER.info("signal fired %s %s %s", signal.symbol, signal.strategy_name, signal.direction.value)
                await alerts.signal_alert(signal)
            if LATENCY_HIST is not None:
                LATENCY_HIST.observe(0.01)
            latency_summary = latency.summary(venue)
            venue_health = health.score(venue, latency_summary, veto_failure_rate=sum(state.suppression_counts.values()) / max(len(state.snapshots), 1))
            http_server.status = {"status": "ok", "venue": venue, "health": venue_health.score}
            if venue_health.score < settings.config["ops"].get("health_alert_threshold", 60):
                await alerts.health_alert(venue_health)
    finally:
        await bot.stop()
        await http_server.stop()
        await news_guard.close()
        await external_client.close()
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
