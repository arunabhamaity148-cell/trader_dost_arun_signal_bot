from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any

try:
    import resource
except Exception:  # noqa: BLE001
    resource = None

from trader_dost_arun.core.config import Settings, load_settings
from trader_dost_arun.core.models import LiquidationEvent, MarketSnapshot, Trade
from trader_dost_arun.core.operator_state import OperatorState
from trader_dost_arun.core.persistence import PositionStore
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalDataClient
from trader_dost_arun.data.manager import ConnectorManager
from trader_dost_arun.features.calculations import compute_features
from trader_dost_arun.newsguard.guard import NewsGuard
from trader_dost_arun.ops.alerts import TelegramAlerter
from trader_dost_arun.ops.health import LATENCY_HIST, SIGNAL_COUNTER, VETO_COUNTER, HealthScorer, OpsHttpServer
from trader_dost_arun.ops.latency import LatencyMonitor
from trader_dost_arun.ops.logging_utils import CooldownDeduper, configure_logging, get_logging_queue_snapshot
from trader_dost_arun.ops.telegram_bot import TelegramAdminBot
from trader_dost_arun.signals.engine import SignalEngine

LOGGER = logging.getLogger(__name__)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _current_rss_mb() -> float:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/status", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return round(float(line.split()[1]) / 1024.0, 2)
        if sys.platform == "win32":
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            # GetCurrentProcess returns a HANDLE (pointer-sized: 8 bytes on 64-bit
            # Windows) as the pseudo-handle -1. Without explicit argtypes/restype,
            # ctypes assumes the default c_int (4 bytes) return type, truncating
            # that handle. GetProcessMemoryInfo's first arg is then read with the
            # wrong width too, so the call silently fails (or returns 0) on every
            # 64-bit Windows run and the except clause below swallowed it,
            # producing rss_mb=0.00 in every runtime_summary log line. Declaring
            # the correct ctypes signatures fixes this.
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.GetCurrentProcess.argtypes = []
            psapi.GetProcessMemoryInfo.restype = ctypes.c_int
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                ctypes.c_ulong,
            ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return round(float(counters.WorkingSetSize) / (1024.0 * 1024.0), 2)
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if usage > 0:
                divisor = 1024.0 if sys.platform != "darwin" else 1024.0 * 1024.0
                return round(float(usage) / divisor, 2)
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.0


@dataclass(slots=True)
class RuntimeStats:
    started_at_monotonic: float = field(default_factory=monotonic)
    queue_events: Counter[str] = field(default_factory=Counter)
    signals_evaluated: int = 0
    signals_emitted: int = 0
    healthy_snapshot_evaluations: int = 0
    stale_snapshot_blocks: int = 0
    signals_blocked_by_reason: Counter[str] = field(default_factory=Counter)
    reconnect_count_by_venue: Counter[str] = field(default_factory=Counter)
    reconnect_reason_distribution: Counter[str] = field(default_factory=Counter)
    unexpected_exceptions: list[str] = field(default_factory=list)
    peak_task_count: int = 0
    queue_high_water_mark: int = 0
    evaluation_latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=5000))
    event_loop_lag_ms: deque[float] = field(default_factory=lambda: deque(maxlen=5000))
    rss_mb_samples: deque[float] = field(default_factory=lambda: deque(maxlen=1440))
    signal_alerts_failed: int = 0


class SignalEvaluationScheduler:
    def __init__(self, callback, min_interval_seconds: float = 1.0, max_concurrent: int = 4) -> None:
        self.callback = callback
        self.min_interval_seconds = max(min_interval_seconds, 0.05)
        self.max_concurrent = max(1, max_concurrent)
        self._dirty: dict[str, tuple[str, str]] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._last_run: dict[str, float] = {}
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    def _key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    async def start(self) -> None:
        if self._loop_task is None:
            self._stop.clear()
            self._loop_task = asyncio.create_task(self._loop(), name="signal-eval-scheduler")

    def notify(self, venue: str, symbol: str) -> None:
        self._dirty[self._key(venue, symbol)] = (venue, symbol)
        self._wake.set()

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        for task in list(self._running.values()):
            task.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)
        self._running.clear()

    async def _loop(self) -> None:
        tick_seconds = min(self.min_interval_seconds / 2, 0.25)
        while not self._stop.is_set():
            self._wake.clear()
            now = monotonic()
            for key, pair in list(self._dirty.items()):
                if key in self._running:
                    continue
                if now - self._last_run.get(key, 0.0) < self.min_interval_seconds:
                    continue
                self._dirty.pop(key, None)
                task = asyncio.create_task(self._run_one(key, *pair), name=f"signal-eval:{key}")
                self._running[key] = task
                task.add_done_callback(lambda finished, task_key=key: self._running.pop(task_key, None))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=tick_seconds)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise

    async def _run_one(self, key: str, venue: str, symbol: str) -> None:
        del key
        async with self._semaphore:
            self._last_run[self._key(venue, symbol)] = monotonic()
            await self.callback(venue, symbol)


class TradingApplication:
    def __init__(self, project_root: Path, settings: Settings | None = None) -> None:
        self.project_root = project_root
        configure_logging(project_root)
        self.settings = settings or load_settings(project_root)
        self._apply_runtime_defaults()
        self.state = MarketStateStore(maxlen=self.settings.config["system"]["history_size"])
        self.latency = LatencyMonitor()
        self.health = HealthScorer()
        self.stats = RuntimeStats()
        self.alerts = TelegramAlerter(
            self.settings.telegram_token,
            self.settings.telegram_chat_id,
            self.settings.config.get("telegram", {}).get("counter_db", "./data/signal_counter.sqlite3"),
        )
        self.external_client = ExternalDataClient(refresh_seconds=self.settings.config.get("external", {}).get("refresh_seconds", 180))
        news_cfg = self.settings.config.setdefault("news_guard", {})
        news_cfg.setdefault("fred_api_key", os.getenv("FRED_API_KEY", ""))
        news_cfg.setdefault("whale_monitor", {})
        if "api_key" not in news_cfg["whale_monitor"]:
            news_cfg["whale_monitor"]["api_key"] = os.getenv("ETHERSCAN_API_KEY", "")
        self.news_guard = NewsGuard(self.settings.config, self.external_client.client)
        self.position_store = PositionStore(self.settings.config.get("positions", {}).get("db_path", "./data/positions.sqlite3"))
        # ONE shared operator-toggles object. The signal engine reads pause/resume
        # from it; the admin bot writes to it. This closes the wiring gap that made
        # /pause and /resume silently no-ops.
        self.operator_state = OperatorState(self.settings.config.get("ops", {}).get("bot_state_path", "./data/bot_state.json"))
        self.signal_engine = SignalEngine(self.settings.config, news_guard=self.news_guard, position_store=self.position_store, operator_state=self.operator_state)
        # Rebuild live win-rate/payoff-ratio per strategy from real closed-trade
        # history instead of leaving every strategy at the neutral prior
        # (win_rate=0.5, payoff_ratio=1.0) until enough fresh trades close
        # after this restart. See MarketStateStore.rebuild_performance_from_history.
        self.state.rebuild_performance_from_history(self.position_store.get_closed_realized_r_by_strategy())
        self.manager = ConnectorManager(self.settings.config, self.latency)
        # Bind the ops/health server to a private interface only by default - exposing
        # the full internal state (/health, /metrics) on 0.0.0.0 is a disclosure risk.
        ops_bind = self.settings.config.get("ops", {}).get("bind_host", "127.0.0.1")
        self.http_server = OpsHttpServer(port=int(self.settings.config.get("ops", {}).get("health_port", 8080)), host=ops_bind)
        self.bot = TelegramAdminBot(
            self.settings.telegram_token,
            os.getenv("TELEGRAM_ADMIN_CHAT_ID", self.settings.config.get("telegram", {}).get("admin_chat_id", "")),
            position_store=self.position_store,
            operator_state=self.operator_state,
            engine_stats_provider=self.signal_engine.engine_stats,
        )
        self.queue: asyncio.Queue | None = None
        self._stop = asyncio.Event()
        self._stopping = False
        self._background_tasks: list[asyncio.Task] = []
        self._evaluation_scheduler = SignalEvaluationScheduler(
            self._evaluate_symbol,
            min_interval_seconds=float(self.settings.config["system"].get("signal_evaluation_interval_seconds", 1.0)),
            max_concurrent=int(self.settings.config["system"].get("signal_evaluation_concurrency", 4)),
        )
        self._suppression_log_deduper = CooldownDeduper(default_cooldown_seconds=float(self.settings.config.get("ops", {}).get("suppression_log_cooldown_seconds", 60)))
        self._suppression_summary_counts: Counter[str] = Counter()
        self._suppression_summary_started = monotonic()
        self._runtime_summary_last = monotonic()

    def _apply_runtime_defaults(self) -> None:
        system_cfg = self.settings.config.setdefault("system", {})
        system_cfg.setdefault("signal_evaluation_interval_seconds", 1.0)
        system_cfg.setdefault("signal_evaluation_concurrency", 4)
        system_cfg.setdefault("market_queue_maxsize", 5000)
        system_cfg.setdefault("market_queue_snapshot_capacity_ratio", 0.7)
        ops_cfg = self.settings.config.setdefault("ops", {})
        ops_cfg.setdefault("health_refresh_seconds", 1.0)
        ops_cfg.setdefault("suppression_log_cooldown_seconds", 60)
        ops_cfg.setdefault("suppression_summary_window_seconds", 60)
        ops_cfg.setdefault("runtime_summary_seconds", 60)
        vetoes_cfg = self.settings.config.setdefault("vetoes", {})
        vetoes_cfg.setdefault("freshness_quorum", {"min_sources": 2})

    async def start(self) -> None:
        if self.queue is not None:
            return
        # news_guard.start() pre-warms the sentence-transformer embedding model
        # (a one-time blocking-ish load) before manager.start() opens the
        # exchange websockets. Previously the model loaded lazily on first use,
        # which landed in the same window as the initial snapshot flood from
        # the just-opened connections and contributed to the large one-time
        # burst of dropped/coalesced snapshots seen at startup.
        await self.news_guard.start()
        self.queue = await self.manager.start()
        await self.http_server.start()
        await self.external_client.start()
        await self.bot.start()
        await self._evaluation_scheduler.start()
        self._log_telegram_status()
        self._background_tasks = [
            asyncio.create_task(self._consume_market_data(), name="market-data-consumer"),
            asyncio.create_task(self._health_loop(), name="health-loop"),
            asyncio.create_task(self._event_loop_monitor(), name="event-loop-monitor"),
        ]

    def _log_telegram_status(self) -> None:
        if self.settings.telegram_token and self.settings.telegram_chat_id:
            LOGGER.info("Telegram ENABLED - signal alerts configured")
        elif not self.settings.telegram_token:
            LOGGER.info("Telegram DISABLED - missing bot token")
        else:
            LOGGER.info("Telegram DISABLED - missing chat id")

    def _record_suppression(self, reason: str, count: int = 1) -> None:
        if count <= 0:
            return
        self._suppression_summary_counts[reason] += count

    def _state_sizes(self) -> dict[str, int]:
        return {
            "snapshots": sum(len(queue) for queue in self.state.snapshots.values()),
            "trades": sum(len(queue) for queue in self.state.trades.values()),
            "liquidations": sum(len(queue) for queue in self.state.liquidations.values()),
        }

    def _cache_sizes(self) -> dict[str, int]:
        cache_method = getattr(self.news_guard, "cache_sizes", None)
        caches = cache_method() if callable(cache_method) else {}
        caches["market_state_symbols"] = len(self.state.snapshots)
        return caches

    def _topology(self) -> dict[str, list[list[str]]]:
        topology_method = getattr(self.manager, "topology", None)
        if callable(topology_method):
            return topology_method()
        return {venue: [[symbol] for symbol in self.manager.enabled_symbols] for venue in getattr(self.manager, "enabled_venues", [])}

    def _maybe_emit_summary_logs(self) -> None:
        now = monotonic()
        suppression_window = float(self.settings.config.get("ops", {}).get("suppression_summary_window_seconds", 60))
        if self._suppression_summary_counts and now - self._suppression_summary_started >= suppression_window:
            for reason, total in sorted(self._suppression_summary_counts.items()):
                LOGGER.info(
                    "event=signal_suppression_summary window_sec=%s reason=%s total=%s",
                    int(suppression_window),
                    reason,
                    total,
                )
            self._suppression_summary_counts.clear()
            self._suppression_summary_started = now
        runtime_window = float(self.settings.config.get("ops", {}).get("runtime_summary_seconds", 60))
        if now - self._runtime_summary_last < runtime_window:
            return
        snapshot = self.runtime_snapshot()
        LOGGER.info(
            "event=runtime_summary window_sec=%s rss_mb=%.2f queue_depth=%s queue_hwm=%s socket_count=%s task_count=%s reconnects=%s queue_overload=%s caches=%s alerts_failed=%s telegram_consecutive_failures=%s",
            int(runtime_window),
            snapshot["rss_mb"],
            snapshot["queue_depth"],
            snapshot["queue_high_water_mark"],
            snapshot["socket_count"],
            snapshot["task_count"],
            snapshot["reconnect_count_by_venue"],
            snapshot["queue_overload"],
            snapshot["cache_sizes"],
            snapshot["signal_alerts_failed"],
            snapshot["telegram_consecutive_send_failures"],
        )
        self._runtime_summary_last = now

    def install_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM so the process shuts down gracefully on a
        VPS stop signal (systemd/docker send SIGTERM). Without this, SIGTERM was
        not handled and Python would terminate immediately mid-write. On Windows,
        add_signal_handler only supports SIGINT; SIGTERM falls back to the
        default, which is caught by the KeyboardInterrupt handler in __main__.
        """
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(__import__("signal"), sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, self.request_shutdown, sig_name)
            except (NotImplementedError, RuntimeError, ValueError):
                # Windows event loops don't support add_signal_handler except SIGINT
                # via Ctrl+C; that's already covered by the KeyboardInterrupt guard.
                pass

    def request_shutdown(self, sig_name: str = "unknown") -> None:
        LOGGER.info("shutdown signal received (%s); stopping gracefully", sig_name)
        if not self._stopping:
            self._stop.set()

    async def run_forever(self) -> None:
        await self.start()
        self.install_signal_handlers()
        try:
            await self._stop.wait()
        except asyncio.CancelledError:
            LOGGER.info("shutdown requested")
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._stop.set()
        try:
            await self._evaluation_scheduler.stop()
            for task in self._background_tasks:
                task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
            await self.bot.stop()
            await self.http_server.stop()
            # Close the pooled Telegram client if the alerter exposes aclose().
            alerter_close = getattr(self.alerts, "aclose", None)
            if callable(alerter_close):
                try:
                    await alerter_close()
                except Exception:  # noqa: BLE001 - shutdown must never crash
                    LOGGER.exception("telegram alerter close failed")
            await self.news_guard.close()
            await self.external_client.close()
            await self.manager.stop()
            self.queue = None
        finally:
            self._stopping = False

    async def _consume_market_data(self) -> None:
        assert self.queue is not None
        while not self._stop.is_set():
            item = await self.queue.get()
            self.stats.queue_high_water_mark = max(self.stats.queue_high_water_mark, self.queue.qsize())
            try:
                should_evaluate = False
                if isinstance(item, MarketSnapshot):
                    self.state.add_snapshot(item)
                    self.stats.queue_events["snapshot"] += 1
                    await self.signal_engine.update_open_positions(item.venue, item.symbol, self.state)
                    should_evaluate = True
                elif isinstance(item, Trade):
                    self.state.add_trade(item)
                    self.stats.queue_events["trade"] += 1
                elif isinstance(item, LiquidationEvent):
                    self.state.add_liquidation(item)
                    self.stats.queue_events["liquidation"] += 1
                    should_evaluate = True
                venue = item.venue
                symbol = item.symbol
                if should_evaluate:
                    self._evaluation_scheduler.notify(venue, symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("market data consumer failed for %s:%s", getattr(item, "venue", "unknown"), getattr(item, "symbol", "unknown"))
                self.stats.unexpected_exceptions.append(type(exc).__name__)

    async def _evaluate_symbol(self, venue: str, symbol: str) -> None:
        view = self.state.view(venue, symbol)
        if len(view.snapshots) < self.settings.config["system"]["min_snapshots_before_signals"]:
            return
        peers = self.state.peer_views(symbol, venue)
        freshness = self.state.freshness(
            venue,
            symbol,
            max_age_seconds=float(self.settings.config["vetoes"]["exchange_instability"].get("max_feed_lag_seconds", 2)),
            min_sources=int(self.settings.config["vetoes"].get("freshness_quorum", {}).get("min_sources", 2)),
        )
        started = perf_counter()
        before = Counter(self.state.suppression_counts)
        try:
            feature_map, peer_features = await asyncio.to_thread(self._build_feature_inputs, view, peers)
            feature_map.values.update(
                {
                    "peer_fresh_source_count": len(freshness.fresh_sources),
                    "peer_total_source_count": freshness.total_sources,
                    "peer_quorum_met": freshness.quorum_met,
                    "own_snapshot_age_seconds": freshness.own_age_seconds if freshness.own_age_seconds is not None else 999.0,
                    "freshest_peer_age_seconds": freshness.freshest_age_seconds if freshness.freshest_age_seconds is not None else 999.0,
                }
            )
            external = self.external_client.current_context()
            feature_map.values.update(
                {
                    "core_age_seconds": freshness.own_age_seconds if freshness.own_age_seconds is not None else 999.0,
                    "enrichment_age_seconds": freshness.own_enrichment_age_seconds if freshness.own_enrichment_age_seconds is not None else 999.0,
                    "freshness_rejection_reason": freshness.freshness_rejection_reason or "",
                }
            )
            signals = await self.signal_engine.evaluate(venue, symbol, feature_map, self.state, peer_features, external)
            if freshness.quorum_met and (freshness.own_age_seconds or 0.0) <= float(self.settings.config["vetoes"]["exchange_instability"].get("max_feed_lag_seconds", 2)):
                self.stats.healthy_snapshot_evaluations += 1
            self.stats.signals_evaluated += max(len(signals), 1)
            for signal in signals:
                if signal.direction.value == "flat" or signal.suppressed_reason:
                    reason = signal.suppressed_reason or "flat_signal"
                    if VETO_COUNTER is not None and signal.suppressed_reason:
                        VETO_COUNTER.labels(reason=signal.suppressed_reason).inc()
                    self.stats.signals_blocked_by_reason[reason] += 1
                    if reason == "stale_snapshot":
                        self.stats.stale_snapshot_blocks += 1
                    self._record_suppression(reason)
                    continue
                if SIGNAL_COUNTER is not None:
                    SIGNAL_COUNTER.inc()
                self.stats.signals_emitted += 1
                LOGGER.info("signal fired %s %s %s", signal.symbol, signal.strategy_name, signal.direction.value)
                delivery_result = await self.alerts.signal_alert(signal)
                if delivery_result == "failed":
                    self.stats.signal_alerts_failed += 1
                    # Loud on purpose: a real-money trade signal that failed
                    # to reach Telegram must never look identical to a
                    # successfully delivered one in the logs. ERROR (not
                    # WARNING) so it stands out, and it escalates further
                    # below if delivery keeps failing (e.g. an expired
                    # token), since that means EVERY signal from here on is
                    # silently not reaching the user.
                    LOGGER.error(
                        "ALERT DELIVERY FAILED for signal %s %s %s - consecutive_failures=%s last_error=%s",
                        signal.symbol, signal.strategy_name, signal.direction.value,
                        self.alerts.consecutive_send_failures, self.alerts.last_send_error,
                    )
                    if self.alerts.consecutive_send_failures >= 3:
                        LOGGER.critical(
                            "TELEGRAM ALERTS HAVE FAILED %s TIMES IN A ROW - signals are being generated but "
                            "NOT reaching you. Check the bot token/chat id and network connectivity.",
                            self.alerts.consecutive_send_failures,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("signal evaluation failed for %s:%s", venue, symbol)
            self.stats.unexpected_exceptions.append(type(exc).__name__)
        finally:
            after = Counter(self.state.suppression_counts)
            for reason, count in (after - before).items():
                self.stats.signals_blocked_by_reason[reason] += count
                if reason == "stale_snapshot":
                    self.stats.stale_snapshot_blocks += count
                if VETO_COUNTER is not None:
                    VETO_COUNTER.labels(reason=reason).inc(count)
                self._record_suppression(reason, count=count)
            elapsed_seconds = perf_counter() - started
            self.stats.evaluation_latency_ms.append(elapsed_seconds * 1000)
            if LATENCY_HIST is not None:
                LATENCY_HIST.observe(elapsed_seconds)

    def _build_feature_inputs(self, view: Any, peers: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        feature_map = compute_features(view, peers)
        # Peer features only need the fields the VetoEngine/strategies actually
        # read (premium, dispersion) and cross-venue freshness. Recomputing the
        # entire feature surface for every peer was the single largest hot-path
        # cost; we now only materialize what is required.
        def _minimal(view_own: Any) -> Any:
            if view_own is None or not getattr(view_own, "snapshots", None):
                return None
            latest = view_own.snapshots[-1]
            from trader_dost_arun.core.models import FeatureSet
            from datetime import datetime, timezone
            values = {
                "premium": float(latest.premium) if latest.premium is not None else 0.0,
                "delta_oi": abs(float(latest.open_interest) - (float(view_own.snapshots[-2].open_interest) if len(view_own.snapshots) > 1 and view_own.snapshots[-2].open_interest else float(latest.open_interest))) if latest.open_interest is not None else 0.0,
            }
            return FeatureSet(venue=latest.venue, symbol=latest.symbol, timestamp=latest.arrival_time, values=values)
        peer_features: dict[str, Any] = {}
        for pv, pw in peers.items():
            if pw.snapshots:
                peer_features[pv] = _minimal(pw)
        return feature_map, peer_features

    async def _event_loop_monitor(self) -> None:
        interval_seconds = float(self.settings.config.get("ops", {}).get("event_loop_lag_sample_seconds", 0.5))
        target = monotonic() + interval_seconds
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval_seconds)
                break
            except asyncio.TimeoutError:
                now = monotonic()
                lag_ms = max((now - target) * 1000, 0.0)
                self.stats.event_loop_lag_ms.append(lag_ms)
                target = now + interval_seconds

    async def _health_loop(self) -> None:
        refresh_seconds = float(self.settings.config.get("ops", {}).get("health_refresh_seconds", 1.0))
        threshold = float(self.settings.config.get("ops", {}).get("health_alert_threshold", 60))
        while not self._stop.is_set():
            try:
                venue_payload: dict[str, Any] = {}
                overall_status = "healthy"
                total_snapshots = max(sum(len(queue) for queue in self.state.snapshots.values()), 1)
                veto_failure_rate = sum(self.state.suppression_counts.values()) / total_snapshots
                for venue in self.manager.enabled_venues:
                    latency_summary = self.latency.summary(venue)
                    venue_health = self.health.score(venue, latency_summary, veto_failure_rate=veto_failure_rate)
                    venue_payload[venue] = {
                        "score": venue_health.score,
                        "status": venue_health.status,
                        "p95_latency_ms": venue_health.p95_latency_ms,
                        "stale_seconds": venue_health.stale_seconds,
                        "reconnect_count": venue_health.reconnect_count,
                        "sample_count": venue_health.sample_count,
                    }
                    if venue_health.status == "degraded" and venue_health.score < threshold:
                        await self.alerts.health_alert(venue_health)
                    if venue_health.status == "degraded":
                        overall_status = "degraded"
                    elif venue_health.status in {"starting", "warmup"} and overall_status != "degraded":
                        overall_status = "starting"
                phase = overall_status if venue_payload else "starting"
                current_queue_depth = self.queue.qsize() if self.queue is not None else 0
                event_loop_lag_samples = list(self.stats.event_loop_lag_ms)
                network_status = self.latency.network_status()
                rss_mb = _current_rss_mb()
                self.stats.rss_mb_samples.append(rss_mb)
                logging_queue = get_logging_queue_snapshot()
                state_sizes = self._state_sizes()
                cache_sizes = self._cache_sizes()
                queue_overload = self.queue.snapshot() if self.queue is not None and hasattr(self.queue, "snapshot") else {}
                if network_status["state"] == "degraded":
                    overall_status = "degraded"
                self.http_server.status = {
                    "status": "degraded" if phase == "degraded" or network_status["state"] == "degraded" else "ok",
                    "phase": phase,
                    "venues": venue_payload,
                    "network": network_status,
                    "task_count": len(asyncio.all_tasks()),
                    "socket_count": self.manager.socket_count,
                    "queue_depth": current_queue_depth,
                    "queue_high_water_mark": self.stats.queue_high_water_mark,
                    "queue_capacity": self.queue.maxsize if self.queue is not None else 0,
                    "event_loop_lag_p95_ms": _percentile(event_loop_lag_samples, 0.95),
                    "event_loop_lag_max_ms": max(event_loop_lag_samples, default=0.0),
                    "rss_mb": rss_mb,
                    "rss_peak_mb": max(self.stats.rss_mb_samples, default=rss_mb),
                    "logging": logging_queue,
                    "cache_sizes": cache_sizes,
                    "state_sizes": state_sizes,
                    "queue_overload": queue_overload,
                    "topology": self._topology(),
                }
                self.stats.peak_task_count = max(self.stats.peak_task_count, len(asyncio.all_tasks()))
                latency_snapshot = self.latency.runtime_snapshot()
                self.stats.reconnect_count_by_venue = Counter(latency_snapshot.get("reconnect_count_by_venue", {}))
                self.stats.reconnect_reason_distribution = Counter(latency_snapshot.get("reconnect_reason_distribution", {}))
                self._maybe_emit_summary_logs()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("health loop failed")
                self.stats.unexpected_exceptions.append(type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=refresh_seconds)
            except asyncio.TimeoutError:
                continue

    def runtime_snapshot(self) -> dict[str, Any]:
        duration = max(monotonic() - self.stats.started_at_monotonic, 0.0)
        latency_snapshot = self.latency.runtime_snapshot()
        event_loop_lag_samples = list(self.stats.event_loop_lag_ms)
        evaluation_latency_samples = list(self.stats.evaluation_latency_ms)
        total_events = sum(self.stats.queue_events.values())
        logging_queue = get_logging_queue_snapshot()
        state_sizes = self._state_sizes()
        cache_sizes = self._cache_sizes()
        queue_overload = self.queue.snapshot() if self.queue is not None and hasattr(self.queue, "snapshot") else {}
        rss_mb = _current_rss_mb()
        return {
            "runtime_duration_seconds": duration,
            "enabled_venues": self.manager.enabled_venues,
            "enabled_symbols": self.manager.enabled_symbols,
            "topology": self._topology(),
            "socket_count": self.manager.socket_count,
            "task_count": len(asyncio.all_tasks()),
            "peak_task_count": self.stats.peak_task_count,
            "queue_events": dict(self.stats.queue_events),
            "queue_depth": self.queue.qsize() if self.queue is not None else 0,
            "queue_capacity": self.queue.maxsize if self.queue is not None else 0,
            "queue_high_water_mark": self.stats.queue_high_water_mark,
            "events_processed": total_events,
            "events_processed_per_second": total_events / duration if duration else 0.0,
            "reconnect_count_by_venue": latency_snapshot.get("reconnect_count_by_venue", {}),
            "reconnect_reason_distribution": latency_snapshot.get("reconnect_reason_distribution", {}),
            "recent_reconnects": latency_snapshot.get("recent_reconnects", []),
            "network": latency_snapshot.get("network", {}),
            "stale_snapshot_blocks": self.stats.stale_snapshot_blocks,
            "healthy_snapshot_evaluations": self.stats.healthy_snapshot_evaluations,
            "signals_evaluated": self.stats.signals_evaluated,
            "signals_emitted": self.stats.signals_emitted,
            "signal_alerts_failed": self.stats.signal_alerts_failed,
            "telegram_consecutive_send_failures": self.alerts.consecutive_send_failures,
            "telegram_last_send_error": self.alerts.last_send_error,
            "evaluation_latency_p95_ms": _percentile(evaluation_latency_samples, 0.95),
            "evaluation_latency_max_ms": max(evaluation_latency_samples, default=0.0),
            "event_loop_lag_p95_ms": _percentile(event_loop_lag_samples, 0.95),
            "event_loop_lag_max_ms": max(event_loop_lag_samples, default=0.0),
            "signals_blocked_by_reason": dict(self.stats.signals_blocked_by_reason),
            "unexpected_exceptions": list(self.stats.unexpected_exceptions),
            "logging": logging_queue,
            "state_sizes": state_sizes,
            "cache_sizes": cache_sizes,
            "queue_overload": queue_overload,
            "rss_mb": rss_mb,
            "rss_peak_mb": max(self.stats.rss_mb_samples, default=rss_mb),
            "health": self.http_server.status,
        }


async def main() -> None:
    project_root = Path(__file__).resolve().parent
    app = TradingApplication(project_root)
    await app.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Fallback when SIGINT isn't delivered via add_signal_handler (Windows
        # event loops). The graceful stop in run_forever() handles the work.
        print("Interrupted; shutting down.", flush=True)
