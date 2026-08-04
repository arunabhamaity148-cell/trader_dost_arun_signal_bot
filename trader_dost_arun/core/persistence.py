from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trader_dost_arun.core.models import Direction, HypotheticalPosition, Signal

LOGGER = logging.getLogger(__name__)


class PositionStore:
    """SQLite-backed position persistence for open and closed signals.

    Resilience: a corrupt/unreadable database must never crash boot or the hot
    path. Reads return empty structures on failure; writes log and continue.
    WAL journal mode improves crash durability and read/write concurrency, and a
    busy_timeout avoids SQLITE_BUSY storms if two writers ever touch the file.
    """

    def __init__(self, db_path: str | Path = "./data/positions.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._degraded = False
        try:
            self._init_schema()
        except Exception:  # noqa: BLE001
            self._degraded = True
            LOGGER.error("positions DB init failed at %s; running degraded (no persistence)", self.db_path, exc_info=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

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
        if self._degraded:
            return -1
        signal = position.signal
        try:
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
                row_id = int(cursor.lastrowid)
                position.db_id = row_id
                return row_id
        except Exception:  # noqa: BLE001 - a persistence hiccup must not crash the engine
            LOGGER.error("failed to persist position %s:%s", signal.venue, signal.symbol, exc_info=True)
            return -1

    def load_open_positions(self) -> list[HypotheticalPosition]:
        if self._degraded:
            return []
        try:
            return self._load_open_positions()
        except Exception:  # noqa: BLE001 - corrupt DB must not crash boot; treat as no history
            LOGGER.error("failed to load open positions from %s; starting empty", self.db_path, exc_info=True)
            return []

    def _load_open_positions(self) -> list[HypotheticalPosition]:
        rows: list[HypotheticalPosition] = []
        with self._connect() as conn:
            for row in conn.execute(
                """
                SELECT id, venue, symbol, strategy_name, direction, entry, stop, targets_json,
                       opened_at, regime, confidence, metadata_json
                FROM positions WHERE closed_at IS NULL ORDER BY opened_at ASC
                """
            ):
                row_id, venue, symbol, strategy_name, direction, entry, stop, targets_json, opened_at, regime, confidence, metadata_json = row
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
                rows.append(HypotheticalPosition(signal=signal, opened_at=datetime.fromisoformat(opened_at), db_id=int(row_id)))
        return rows

    def close_position_by_id(self, position_id: int, exit_price: float, realized_r: float, exit_reason: str) -> None:
        """Close exactly one position row by its primary key."""
        if self._degraded:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE positions
                    SET closed_at = ?, exit_price = ?, realized_r = ?, exit_reason = ?
                    WHERE id = ? AND closed_at IS NULL
                    """,
                    (datetime.now(timezone.utc).isoformat(), exit_price, realized_r, exit_reason, position_id),
                )
        except Exception:  # noqa: BLE001
            LOGGER.error("failed to close position id=%s", position_id, exc_info=True)

    def close_position(self, symbol: str, venue: str, exit_price: float, realized_r: float, exit_reason: str) -> None:
        """Legacy symbol+venue based close. WARNING: matches every open row for
        this symbol+venue. Prefer close_position_by_id when possible."""
        if self._degraded:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE positions
                    SET closed_at = ?, exit_price = ?, realized_r = ?, exit_reason = ?
                    WHERE symbol = ? AND venue = ? AND closed_at IS NULL
                    """,
                    (datetime.now(timezone.utc).isoformat(), exit_price, realized_r, exit_reason, symbol, venue),
                )
        except Exception:  # noqa: BLE001
            LOGGER.error("failed to close position %s:%s", venue, symbol, exc_info=True)

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        if self._degraded:
            return []
        try:
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
        except Exception:  # noqa: BLE001
            LOGGER.error("failed to read position history", exc_info=True)
            return []

    def get_closed_realized_r_by_strategy(self) -> dict[str, list[float]]:
        """All closed trades' realized R, grouped by strategy_name (no row cap)."""
        if self._degraded:
            return {}
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    SELECT strategy_name, realized_r
                    FROM positions
                    WHERE closed_at IS NOT NULL AND realized_r IS NOT NULL
                    ORDER BY opened_at ASC
                    """
                )
                grouped: dict[str, list[float]] = {}
                for strategy_name, realized_r in cur.fetchall():
                    grouped.setdefault(strategy_name, []).append(float(realized_r))
                return grouped
        except Exception:  # noqa: BLE001 - treated as "no history" rather than crash
            LOGGER.error("failed to rebuild performance history from %s", self.db_path, exc_info=True)
            return {}
