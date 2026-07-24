from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


class LLMNewsClassifier:
    """GLM-4 batch classifier with SQLite cache and keyword fallback."""

    def __init__(self, db_path: str | Path = "./data/news_llm_cache.sqlite3", command: list[str] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.command = command or ["z-ai-web-dev-sdk", "classify-news"]
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS classifications(event_hash TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def _hash(self, event: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(event, sort_keys=True).encode("utf-8")).hexdigest()

    def _fallback(self, event: dict[str, Any]) -> dict[str, Any]:
        text = f"{event.get('title','')} {event.get('summary','')}".lower()
        category = "general"
        severity = 0.25
        sentiment = 0.0
        affected = event.get("symbols", [])
        if any(token in text for token in ["hack", "exploit", "halt", "incident"]):
            category, severity, sentiment = "incident", 0.9, -0.8
        elif any(token in text for token in ["cpi", "fed", "macro", "inflation"]):
            category, severity, sentiment = "macro", 0.8, -0.1
        elif any(token in text for token in ["whale", "deposit", "exchange inflow", "outflow"]):
            category, severity, sentiment = "whale", 0.7, -0.1
        elif any(token in text for token in ["regulator", "sec", "etf approval", "lawsuit"]):
            category, severity, sentiment = "regulatory", 0.75, -0.2
        elif any(token in text for token in ["partnership", "launch", "listing", "upgrade"]):
            category, severity, sentiment = "partnership", 0.6, 0.4
        return {
            "category": category,
            "severity_0_to_1": severity,
            "sentiment_-1_to_1": sentiment,
            "affected_symbols": affected,
            "time_horizon_minutes": 120,
            "confidence": 0.55,
        }

    def classify_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        uncached: list[tuple[str, dict[str, Any]]] = []
        with self._connect() as conn:
            for event in events:
                event_hash = self._hash(event)
                row = conn.execute("SELECT payload FROM classifications WHERE event_hash = ?", (event_hash,)).fetchone()
                if row:
                    outputs.append(json.loads(row[0]))
                else:
                    uncached.append((event_hash, event))
        for start in range(0, len(uncached), 10):
            batch = uncached[start : start + 10]
            batch_outputs = self._run_batch([item[1] for item in batch])
            with self._connect() as conn:
                for (event_hash, _), payload in zip(batch, batch_outputs, strict=False):
                    conn.execute("INSERT OR REPLACE INTO classifications(event_hash, payload) VALUES (?, ?)", (event_hash, json.dumps(payload)))
                    outputs.append(payload)
        return outputs

    def _run_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(self.command, input=json.dumps(events), capture_output=True, text=True, check=True, timeout=30)
            parsed = json.loads(result.stdout)
            if isinstance(parsed, list):
                return parsed
        except Exception:  # noqa: BLE001
            pass
        return [self._fallback(event) for event in events]
