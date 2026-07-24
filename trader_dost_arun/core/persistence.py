from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from trader_dost_arun.core.models import Direction, HypotheticalPosition, Signal


class PositionStore:
    """SQLite-backed position persistence for open and closed signals."""

    def __init__(self, db_path: str | Path = "./data/positions.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    targets_json TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    realized_r REAL,
                    exit_reason TEXT,
                    regime TEXT,
                    confidence REAL,
                    metadata_json TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(closed_at, symbol, venue)")

    def save_position(self, position: HypotheticalPosition) -> int:
        signal = position.signal
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO positions (
                    venue, symbol, strategy_name, direction, entry, stop, targets_json,
                    opened_at, closed_at, exit_price, realized_r, exit_reason, regime,
                    confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.venue,
                    signal.symbol,
                    signal.strategy_name,
                    signal.direction.value,
                    signal.entry,
                    signal.stop,
                    json.dumps(signal.targets),
                    position.opened_at.isoformat(),
                    position.closed_at.isoformat() if position.closed_at else None,
                    position.exit_price,
                    position.realized_r_multiple,
                    position.exit_reason,
                    signal.regime,
                    signal.confidence,
                    json.dumps(signal.metadata, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def load_open_positions(self) -> list[HypotheticalPosition]:
        rows: list[HypotheticalPosition] = []
        with self._connect() as conn:
            for row in conn.execute(
                """
                SELECT id, venue, symbol, strategy_name, direction, entry, stop, targets_json,
                       opened_at, regime, confidence, metadata_json
                FROM positions WHERE closed_at IS NULL ORDER BY opened_at ASC
                """
            ):
                _, venue, symbol, strategy_name, direction, entry, stop, targets_json, opened_at, regime, confidence, metadata_json = row
                signal = Signal(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    venue=venue,
                    direction=Direction(direction),
                    entry=float(entry),
                    stop=float(stop),
                    targets=[float(x) for x in json.loads(targets_json)],
                    confidence=float(confidence or 0.0),
                    advisory_size_fraction=float(json.loads(metadata_json or "{}").get("size_fraction", 0.0)),
                    regime=regime or "unknown",
                    confirmations=[],
                    vetoes_checked={},
                    metadata=json.loads(metadata_json or "{}"),
                    created_at=datetime.fromisoformat(opened_at),
                )
                rows.append(HypotheticalPosition(signal=signal, opened_at=datetime.fromisoformat(opened_at)))
        return rows

    def close_position(self, symbol: str, venue: str, exit_price: float, realized_r: float, exit_reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE positions
                SET closed_at = ?, exit_price = ?, realized_r = ?, exit_reason = ?
                WHERE symbol = ? AND venue = ? AND closed_at IS NULL
                """,
                (datetime.utcnow().isoformat(), exit_price, realized_r, exit_reason, symbol, venue),
            )

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT venue, symbol, strategy_name, direction, entry, stop, targets_json, opened_at,
                       closed_at, exit_price, realized_r, exit_reason, regime, confidence, metadata_json
                FROM positions ORDER BY opened_at DESC LIMIT ?
                """,
                (limit,),
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
