from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from trader_dost_arun.core.models import VenueHealth

try:
    from prometheus_client import Counter, Histogram, generate_latest
except Exception:  # noqa: BLE001
    Counter = Histogram = None
    generate_latest = None

SIGNAL_COUNTER = Counter("signals_total", "Signals emitted") if Counter is not None else None
VETO_COUNTER = Counter("signal_veto_total", "Signals vetoed", ["reason"]) if Counter is not None else None
LATENCY_HIST = Histogram("signal_latency_seconds", "Signal evaluation latency") if Histogram is not None else None


class HealthScorer:
    def score(self, venue: str, latency: dict[str, float], veto_failure_rate: float) -> VenueHealth:
        score = 100.0
        score -= min(latency["p95"] / 100, 25)
        score -= min(latency["stale"] * 2, 25)
        score -= min(veto_failure_rate * 20, 20)
        score -= min(latency["errors"] * 2 + latency["reconnects"], 30)
        return VenueHealth(
            venue=venue,
            score=max(score, 0.0),
            p50_latency_ms=latency["p50"],
            p95_latency_ms=latency["p95"],
            p99_latency_ms=latency["p99"],
            reconnect_count=int(latency["reconnects"]),
            stale_seconds=latency["stale"],
            veto_failure_rate=veto_failure_rate,
            error_rate=latency["errors"],
        )


class OpsHttpServer:
    def __init__(self, port: int = 8080) -> None:
        self.port = port
        self._server: asyncio.base_events.Server | None = None
        self.status: dict[str, object] = {"status": "ok"}

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "0.0.0.0", self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = (await reader.readline()).decode("utf-8", "ignore")
        path = request_line.split(" ")[1] if " " in request_line else "/health"
        if path.startswith("/metrics") and generate_latest is not None:
            body = generate_latest().decode("utf-8")
            content_type = "text/plain"
        else:
            body = json.dumps(self.status)
            content_type = "application/json"
        response = f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n{body}"
        writer.write(response.encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
