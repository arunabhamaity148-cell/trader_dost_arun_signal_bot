from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from statistics import median, quantiles


class LatencyMonitor:
    def __init__(self, max_samples: int = 1000) -> None:
        self.samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))
        self.reconnects: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.last_event: dict[str, datetime] = {}

    def record(self, venue: str, event_time: datetime) -> None:
        now = datetime.now(timezone.utc)
        self.samples[venue].append((now - event_time).total_seconds() * 1000)
        self.last_event[venue] = now

    def reconnect(self, venue: str) -> None:
        self.reconnects[venue] += 1

    def error(self, venue: str) -> None:
        self.errors[venue] += 1

    def summary(self, venue: str) -> dict[str, float]:
        values = list(self.samples[venue])
        if not values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "stale": 999.0, "reconnects": float(self.reconnects[venue]), "errors": float(self.errors[venue])}
        q = quantiles(values, n=100) if len(values) >= 100 else sorted(values) + [values[-1]] * (100 - len(values))
        stale = (datetime.now(timezone.utc) - self.last_event.get(venue, datetime.now(timezone.utc))).total_seconds()
        return {"p50": median(values), "p95": q[94], "p99": q[98], "stale": stale, "reconnects": float(self.reconnects[venue]), "errors": float(self.errors[venue])}
