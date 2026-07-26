from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


class LLMNewsClassifier:
    """GLM-4.6 batch classifier with SQLite cache and keyword fallback."""

    def __init__(self, db_path: str | Path = "./data/news_llm_cache.sqlite3", command: list[str] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.command = command or ["z-ai-web-dev-sdk", "chat.completions.create"]
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
        if not events:
            return []
        cached_payloads: dict[str, dict[str, Any]] = {}
        uncached: list[tuple[str, dict[str, Any]]] = []
        with self._connect() as conn:
            for event in events:
                event_hash = self._hash(event)
                row = conn.execute("SELECT payload FROM classifications WHERE event_hash = ?", (event_hash,)).fetchone()
                if row:
                    cached_payloads[event_hash] = json.loads(row[0])
                else:
                    uncached.append((event_hash, event))
        fresh_payloads: dict[str, dict[str, Any]] = {}
        for start in range(0, len(uncached), 10):
            batch = uncached[start : start + 10]
            batch_outputs = self._run_batch([item[1] for item in batch])
            with self._connect() as conn:
                for (event_hash, _), payload in zip(batch, batch_outputs, strict=False):
                    conn.execute("INSERT OR REPLACE INTO classifications(event_hash, payload) VALUES (?, ?)", (event_hash, json.dumps(payload)))
                    fresh_payloads[event_hash] = payload
        ordered: list[dict[str, Any]] = []
        for event in events:
            event_hash = self._hash(event)
            ordered.append(fresh_payloads.get(event_hash) or cached_payloads.get(event_hash) or self._fallback(event))
        return ordered

    def _request_payload(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "severity_0_to_1": {"type": "number"},
                    "sentiment_-1_to_1": {"type": "number"},
                    "affected_symbols": {"type": "array", "items": {"type": "string"}},
                    "time_horizon_minutes": {"type": "integer"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "category",
                    "severity_0_to_1",
                    "sentiment_-1_to_1",
                    "affected_symbols",
                    "time_horizon_minutes",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
        return {
            "model": "glm-4.6",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify batches of crypto market news. "
                        "Return only JSON matching the provided schema. "
                        "Use categories such as incident, macro, whale, regulatory, partnership, catalyst, or general."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Classify each event and keep output order identical to input.",
                            "events": events,
                            "output_schema": schema,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "news_batch_classification", "schema": schema},
            },
        }

    def _parse_stdout(self, stdout: str, expected: int) -> list[dict[str, Any]] | None:
        if not stdout.strip():
            return None
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            return parsed if len(parsed) == expected else None
        if isinstance(parsed, dict):
            if isinstance(parsed.get("output"), list) and len(parsed["output"]) == expected:
                return parsed["output"]
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if isinstance(content, list):
                    text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                else:
                    text = str(content)
                inner = json.loads(text)
                if isinstance(inner, list) and len(inner) == expected:
                    return inner
        return None

    def _run_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        try:
            result = subprocess.run(
                self.command,
                input=json.dumps(self._request_payload(events), ensure_ascii=False),
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            parsed = self._parse_stdout(result.stdout, len(events))
            if parsed is not None:
                return parsed
        except Exception:  # noqa: BLE001
            pass
        return [self._fallback(event) for event in events]
