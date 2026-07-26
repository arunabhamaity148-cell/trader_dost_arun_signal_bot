from __future__ import annotations

import asyncio
import json

from trader_dost_arun.core.models import VenueHealth

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
except Exception:  # noqa: BLE001
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = Gauge = Histogram = None
    generate_latest = None

SIGNAL_COUNTER = Counter("signals_total", "Signals emitted") if Counter is not None else None
VETO_COUNTER = Counter("signal_veto_total", "Signals vetoed", ["reason"]) if Counter is not None else None
LATENCY_HIST = Histogram("signal_latency_seconds", "Signal evaluation latency") if Histogram is not None else None
HEALTH_SCORE_GAUGE = Gauge("venue_health_score", "Venue health score", ["venue"]) if Gauge is not None else None
HEALTH_STATUS_GAUGE = Gauge("venue_health_status", "Venue health status (0=starting,1=healthy,2=degraded)", ["venue"]) if Gauge is not None else None


class HealthScorer:
    def __init__(self, min_samples_for_healthy: int = 20, stale_seconds_for_degraded: float = 5.0) -> None:
        self.min_samples_for_healthy = min_samples_for_healthy
        self.stale_seconds_for_degraded = stale_seconds_for_degraded

    def score(self, venue: str, latency: dict[str, float], veto_failure_rate: float) -> VenueHealth:
        sample_count = int(latency.get("sample_count", 0))
        if sample_count == 0:
            status = "starting"
        elif sample_count < self.min_samples_for_healthy:
            status = "warmup"
        elif latency["stale"] > self.stale_seconds_for_degraded or latency["errors"] > 0 or latency["reconnects"] > 3:
            status = "degraded"
        else:
            status = "healthy"
        score = 100.0
        score -= min(latency["p95"] / 100, 25)
        score -= min(latency["stale"] * 2, 25)
        score -= min(veto_failure_rate * 20, 20)
        score -= min(latency["errors"] * 2 + latency["reconnects"], 30)
        score = max(score, 0.0)
        if status in {"starting", "warmup"}:
            score = max(score, 80.0)
        health = VenueHealth(
            venue=venue,
            score=score,
            p50_latency_ms=latency["p50"],
            p95_latency_ms=latency["p95"],
            p99_latency_ms=latency["p99"],
            reconnect_count=int(latency["reconnects"]),
            stale_seconds=latency["stale"],
            veto_failure_rate=veto_failure_rate,
            error_rate=latency["errors"],
            status=status,
            sample_count=sample_count,
        )
        if HEALTH_SCORE_GAUGE is not None:
            HEALTH_SCORE_GAUGE.labels(venue=venue).set(health.score)
        if HEALTH_STATUS_GAUGE is not None:
            HEALTH_STATUS_GAUGE.labels(venue=venue).set({"starting": 0, "warmup": 0, "healthy": 1, "degraded": 2}.get(status, 2))
        return health


class OpsHttpServer:
    def __init__(self, port: int = 8080) -> None:
        self.port = port
        self._server: asyncio.base_events.Server | None = None
        self.status: dict[str, object] = {"status": "ok", "phase": "starting", "venues": {}}

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "0.0.0.0", self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = (await reader.readline()).decode("utf-8", "ignore")
        path = request_line.split(" ")[1] if " " in request_line else "/health"
        status_line = "HTTP/1.1 200 OK"
        if path.startswith("/metrics") and generate_latest is not None:
            body_bytes = generate_latest()
            content_type = CONTENT_TYPE_LATEST
        elif path.startswith("/health") or path == "/":
            body_bytes = json.dumps(self.status).encode("utf-8")
            content_type = "application/json"
        else:
            status_line = "HTTP/1.1 404 Not Found"
            body_bytes = b'{"status":"not_found"}'
            content_type = "application/json"
        response_headers = (
            f"{status_line}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(response_headers + body_bytes)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
