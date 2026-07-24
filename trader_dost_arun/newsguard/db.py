from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from trader_dost_arun.newsguard.models import ImpactAssessment, NewsEvent


class EventReplayStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_events (
                    event_id TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT,
                    url TEXT,
                    source_type TEXT,
                    source_name TEXT,
                    category TEXT,
                    severity REAL,
                    sentiment REAL,
                    language TEXT,
                    symbols_json TEXT,
                    entities_json TEXT,
                    lifecycle TEXT,
                    mention_count INTEGER,
                    source_reliability REAL,
                    consensus_score REAL,
                    first_seen_at TEXT,
                    last_seen_at TEXT,
                    cooldown_until TEXT,
                    observed_impact_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS impact_assessments (
                    event_id TEXT,
                    assessed_at TEXT,
                    confidence_multiplier REAL,
                    risk_multiplier REAL,
                    regime_modifier TEXT,
                    suppress INTEGER,
                    cancel INTEGER,
                    delay_seconds INTEGER,
                    reasons_json TEXT
                )
                """
            )

    def upsert_event(self, event: NewsEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO news_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    url=excluded.url,
                    source_type=excluded.source_type,
                    source_name=excluded.source_name,
                    category=excluded.category,
                    severity=excluded.severity,
                    sentiment=excluded.sentiment,
                    language=excluded.language,
                    symbols_json=excluded.symbols_json,
                    entities_json=excluded.entities_json,
                    lifecycle=excluded.lifecycle,
                    mention_count=excluded.mention_count,
                    source_reliability=excluded.source_reliability,
                    consensus_score=excluded.consensus_score,
                    first_seen_at=excluded.first_seen_at,
                    last_seen_at=excluded.last_seen_at,
                    cooldown_until=excluded.cooldown_until,
                    observed_impact_json=excluded.observed_impact_json
                """,
                (
                    event.event_id,
                    event.title,
                    event.summary,
                    event.url,
                    event.source_type,
                    event.source_name,
                    event.category,
                    event.severity,
                    event.sentiment,
                    event.language,
                    json.dumps(event.symbols),
                    json.dumps(event.entities),
                    event.lifecycle,
                    event.mention_count,
                    event.source_reliability,
                    event.consensus_score,
                    event.first_seen_at.isoformat(),
                    event.last_seen_at.isoformat(),
                    event.cooldown_until.isoformat() if event.cooldown_until else None,
                    json.dumps(asdict(event.observed_impact), default=str),
                ),
            )

    def record_assessment(self, event_id: str, assessment: ImpactAssessment) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO impact_assessments VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    assessment.confidence_multiplier,
                    assessment.risk_multiplier,
                    assessment.regime_modifier,
                    int(assessment.suppress),
                    int(assessment.cancel),
                    assessment.delay_seconds,
                    json.dumps(assessment.reasons),
                ),
            )
