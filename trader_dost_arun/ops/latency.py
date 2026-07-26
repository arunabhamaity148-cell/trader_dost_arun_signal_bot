from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any


@dataclass(slots=True)
class ReconnectEvent:
    venue: str
    symbol: str
    connection_id: str
    reason: str
    uptime: float
    last_message_age: float | None
    attempt: int
    backoff: float
    timestamp: datetime


class LatencyMonitor:
    def __init__(self, max_samples: int = 1000, reconnect_history: int = 500) -> None:
        self.samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))
        self.reconnects: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.last_event: dict[str, datetime] = {}
        self.last_feed_event: dict[str, datetime] = {}
        self.feed_reconnects: dict[str, int] = defaultdict(int)
        self.reconnect_reason_counts: Counter[str] = Counter()
        self.reconnect_events: deque[ReconnectEvent] = deque(maxlen=reconnect_history)
        self.active_connections: dict[str, str] = {}
        self.stable_resets: dict[str, int] = defaultdict(int)

    def _feed_key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def record(self, venue: str, event_time: datetime, symbol: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.samples[venue].append(max((now - event_time).total_seconds() * 1000, 0.0))
        self.last_event[venue] = now
        if symbol is not None:
            self.last_feed_event[self._feed_key(venue, symbol)] = now

    def connection_open(self, venue: str, symbol: str, connection_id: str) -> None:
        self.active_connections[self._feed_key(venue, symbol)] = connection_id

    def record_message(self, venue: str, symbol: str) -> None:
        now = datetime.now(timezone.utc)
        self.last_event[venue] = now
        self.last_feed_event[self._feed_key(venue, symbol)] = now

    def reconnect(
        self,
        venue: str,
        symbol: str,
        connection_id: str,
        reason: str,
        uptime: float,
        last_message_age: float | None,
        attempt: int,
        backoff: float,
    ) -> None:
        self.reconnects[venue] += 1
        self.feed_reconnects[self._feed_key(venue, symbol)] += 1
        self.reconnect_reason_counts[reason] += 1
        self.reconnect_events.append(
            ReconnectEvent(
                venue=venue,
                symbol=symbol,
                connection_id=connection_id,
                reason=reason,
                uptime=uptime,
                last_message_age=last_message_age,
                attempt=attempt,
                backoff=backoff,
                timestamp=datetime.now(timezone.utc),
            )
        )

    def stable_connection(self, venue: str, symbol: str) -> None:
        self.stable_resets[self._feed_key(venue, symbol)] += 1

    def error(self, venue: str, symbol: str | None = None) -> None:
        del symbol
        self.errors[venue] += 1

    def _percentile(self, values: list[float], percentile: float) -> float:
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

    def summary(self, venue: str) -> dict[str, float]:
        values = list(self.samples[venue])
        stale = (datetime.now(timezone.utc) - self.last_event.get(venue, datetime.now(timezone.utc))).total_seconds()
        return {
            "p50": median(values) if values else 0.0,
            "p95": self._percentile(values, 0.95),
            "p99": self._percentile(values, 0.99),
            "stale": stale if values else 999.0,
            "reconnects": float(self.reconnects[venue]),
            "errors": float(self.errors[venue]),
            "sample_count": float(len(values)),
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        reconnects_by_venue: dict[str, int] = defaultdict(int)
        for key, value in self.feed_reconnects.items():
            venue, _ = key.split(":", 1)
            reconnects_by_venue[venue] += value
        return {
            "reconnect_count_by_venue": dict(reconnects_by_venue),
            "reconnect_reason_distribution": dict(self.reconnect_reason_counts),
            "feed_reconnects": dict(self.feed_reconnects),
            "stable_retry_resets": dict(self.stable_resets),
            "recent_reconnects": [event.__dict__ for event in self.reconnect_events],
        }
