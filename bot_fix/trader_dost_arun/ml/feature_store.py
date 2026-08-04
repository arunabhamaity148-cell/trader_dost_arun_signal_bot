from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any


class FeatureStore:
    def __init__(self, db_path: str | Path = "./data/features.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_rows (
                    symbol TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    label INTEGER,
                    features_json TEXT NOT NULL,
                    PRIMARY KEY(symbol, strategy_name, ts)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feature_store_symbol_ts ON feature_rows(symbol, ts)")

    def put(self, symbol: str, strategy_name: str, ts: str, features: dict[str, float], label: int | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feature_rows(symbol, strategy_name, ts, label, features_json) VALUES (?, ?, ?, ?, ?)",
                (symbol, strategy_name, ts, label, json.dumps(features, sort_keys=True)),
            )

    def rows(self, symbol: str, strategy_name: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ts, label, features_json FROM feature_rows WHERE symbol = ? AND strategy_name = ? ORDER BY ts ASC",
                (symbol, strategy_name),
            )
            return [{"ts": ts, "label": label, "features": json.loads(payload)} for ts, label, payload in cur.fetchall()]

    def stability_scores(self, symbol: str, strategy_name: str, windows: int = 3) -> dict[str, float]:
        rows = self.rows(symbol, strategy_name)
        if len(rows) < windows * 3:
            return {}
        feature_names = sorted(rows[0]["features"].keys())
        chunk = max(len(rows) // windows, 1)
        rank_sets: list[list[str]] = []
        for idx in range(windows):
            segment = rows[idx * chunk : (idx + 1) * chunk] or rows[-chunk:]
            averages = {name: mean([float(r["features"].get(name, 0.0)) for r in segment]) for name in feature_names}
            rank_sets.append(sorted(feature_names, key=lambda name: abs(averages[name]), reverse=True))
        scores: dict[str, float] = {}
        for name in feature_names:
            positions = [rank.index(name) for rank in rank_sets]
            norm = max(len(feature_names) - 1, 1)
            scores[name] = max(0.0, 1.0 - (max(positions) - min(positions)) / norm)
        return scores

    def select_stable_features(self, symbol: str, strategy_name: str, threshold: float = 0.3) -> list[str]:
        scores = self.stability_scores(symbol, strategy_name)
        return [name for name, score in scores.items() if score >= threshold]
