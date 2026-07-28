from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any


SYSTEMIC_ERROR_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "ReadError",
    "ReadTimeout",
    "TimeoutError",
    "NetworkError",
    "TransportError",
    "gaierror",
    "heartbeat_timeout",
}


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


@dataclass(slots=True)
class NetworkFailureEvent:
    venue: str
    symbol: str
    error_type: str
    timestamp: datetime


class LatencyMonitor:
    def __init__(
        self,
        max_samples: int = 1000,
        reconnect_history: int = 500,
        failure_window_seconds: float = 20.0,
        systemic_min_failures: int = 3,
        systemic_min_venues: int = 2,
        recovery_successes: int = 2,
    ) -> None:
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
        self.failure_window_seconds = failure_window_seconds
        self.systemic_min_failures = systemic_min_failures
        self.systemic_min_venues = systemic_min_venues
        self.recovery_successes = recovery_successes
        self.network_failures: deque[NetworkFailureEvent] = deque(maxlen=200)
        self.network_degraded_since: datetime | None = None
        self.network_degraded_reason: str | None = None
        self.network_recoveries: int = 0
        self.network_state_transitions: list[dict[str, Any]] = []
        self.duplicate_connection_attempts: int = 0

    def _feed_key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _trim_network_failures(self) -> list[NetworkFailureEvent]:
        now = self._utcnow()
        kept = [event for event in self.network_failures if (now - event.timestamp).total_seconds() <= self.failure_window_seconds]
        if len(kept) != len(self.network_failures):
            self.network_failures = deque(kept, maxlen=self.network_failures.maxlen)
        return kept

    def record(self, venue: str, event_time: datetime, symbol: str | None = None) -> None:
        now = self._utcnow()
        self.samples[venue].append(max((now - event_time).total_seconds() * 1000, 0.0))
        self.last_event[venue] = now
        if symbol is not None:
            self.last_feed_event[self._feed_key(venue, symbol)] = now
        self.record_connection_success(venue, symbol)

    def connection_open(self, venue: str, symbol: str, connection_id: str) -> bool:
        feed_key = self._feed_key(venue, symbol)
        current_owner = self.active_connections.get(feed_key)
        if current_owner is not None and current_owner != connection_id:
            self.duplicate_connection_attempts += 1
        self.active_connections[feed_key] = connection_id
        self.record_connection_success(venue, symbol)
        return current_owner in {None, connection_id}

    def connection_closed(self, venue: str, symbol: str, connection_id: str) -> None:
        feed_key = self._feed_key(venue, symbol)
        if self.active_connections.get(feed_key) == connection_id:
            self.active_connections.pop(feed_key, None)

    def record_message(self, venue: str, symbol: str) -> None:
        now = self._utcnow()
        self.last_event[venue] = now
        self.last_feed_event[self._feed_key(venue, symbol)] = now
        self.record_connection_success(venue, symbol)

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
                timestamp=self._utcnow(),
            )
        )

    def stable_connection(self, venue: str, symbol: str) -> None:
        self.stable_resets[self._feed_key(venue, symbol)] += 1

    def error(self, venue: str, symbol: str | None = None) -> None:
        del symbol
        self.errors[venue] += 1

    def record_transport_failure(self, venue: str, symbol: str, error_type: str) -> bool:
        self.errors[venue] += 1
        if error_type not in SYSTEMIC_ERROR_NAMES and not error_type.startswith("connection_closed:10"):
            return False
        now = self._utcnow()
        self.network_recoveries = 0
        self.network_failures.append(NetworkFailureEvent(venue=venue, symbol=symbol, error_type=error_type, timestamp=now))
        recent = self._trim_network_failures()
        unique_venues = {event.venue for event in recent}
        if len(recent) >= self.systemic_min_failures and len(unique_venues) >= self.systemic_min_venues:
            if self.network_degraded_since is None:
                self.network_degraded_since = now
                self.network_degraded_reason = error_type
                self.network_state_transitions.append({"state": "degraded", "timestamp": now.isoformat(), "reason": error_type})
            return True
        return False

    def record_connection_success(self, venue: str, symbol: str | None = None) -> None:
        del venue, symbol
        if self.network_degraded_since is None:
            return
        self.network_recoveries += 1
        if self.network_recoveries >= self.recovery_successes:
            now = self._utcnow()
            self.network_degraded_since = None
            self.network_degraded_reason = None
            self.network_recoveries = 0
            self.network_failures.clear()
            self.network_state_transitions.append({"state": "recovered", "timestamp": now.isoformat(), "reason": "success_threshold"})

    def is_network_degraded(self) -> bool:
        self._trim_network_failures()
        return self.network_degraded_since is not None

    def network_status(self) -> dict[str, Any]:
        recent = self._trim_network_failures()
        return {
            "state": "degraded" if self.network_degraded_since else "healthy",
            "since": self.network_degraded_since.isoformat() if self.network_degraded_since else None,
            "reason": self.network_degraded_reason,
            "recent_failure_count": len(recent),
            "recent_failure_venues": sorted({event.venue for event in recent}),
        }

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
        stale = (self._utcnow() - self.last_event.get(venue, self._utcnow())).total_seconds()
        return {
            "p50": median(values) if values else 0.0,
            "p95": self._percentile(values, 0.95),
            "p99": self._percentile(values, 0.99),
            "stale": stale if values else 999.0,
            "reconnects": float(self.reconnects[venue]),
            "errors": float(self.errors[venue]),
            "sample_count": float(len(values)),
        }

    def _serialize_reconnect_event(self, event: ReconnectEvent) -> dict[str, Any]:
        payload = asdict(event)
        payload["timestamp"] = event.timestamp.isoformat()
        return payload

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
            "recent_reconnects": [self._serialize_reconnect_event(event) for event in self.reconnect_events],
            "network": self.network_status(),
            "active_connections": dict(self.active_connections),
            "duplicate_connection_attempts": self.duplicate_connection_attempts,
            "network_state_transitions": list(self.network_state_transitions),
        }
