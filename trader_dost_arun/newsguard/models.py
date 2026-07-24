from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ObservedImpact:
    price_change_bps: float = 0.0
    open_interest_change_pct: float = 0.0
    funding_change_bps: float = 0.0
    measured_at: datetime | None = None


@dataclass(slots=True)
class NewsEvent:
    event_id: str
    title: str
    summary: str
    url: str
    source_type: str
    source_name: str
    category: str
    severity: float
    sentiment: float
    language: str
    symbols: list[str]
    entities: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    lifecycle: str = "detected"
    mention_count: int = 1
    source_reliability: float = 1.0
    consensus_score: float = 0.0
    cooldown_until: datetime | None = None
    observed_impact: ObservedImpact = field(default_factory=ObservedImpact)


@dataclass(slots=True)
class ImpactAssessment:
    confidence_multiplier: float = 1.0
    risk_multiplier: float = 1.0
    regime_modifier: str | None = None
    suppress: bool = False
    cancel: bool = False
    delay_seconds: int = 0
    reasons: list[str] = field(default_factory=list)
    cooldown_until: datetime | None = None
    active_events: list[NewsEvent] = field(default_factory=list)
