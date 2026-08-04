from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class OperatorState:
    """Single source of truth for operator runtime toggles (paused strategies,
    mute window). Persisted to JSON with atomic write so a crash mid-save can't
    corrupt it, and tolerant on load so a corrupt file never crashes boot.

    This object is SHARED between the Telegram admin bot (which *writes* the
    toggles in response to /pause and /resume) and the signal engine (which
    *reads* them on every evaluation). Previously the two sides used different
    objects (telegram_bot.state vs getattr(news_guard, "paused_strategies", [])),
    so /pause and /resume silently had no effect on the live signal path.
    """

    def __init__(self, state_path: str | Path = "./data/bot_state.json") -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state = self._load()

    def _default(self) -> dict[str, Any]:
        return {"muted_until": 0, "paused_strategies": []}

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt operator state must not crash
            LOGGER.error("operator state unreadable at %s; using defaults", self.state_path, exc_info=True)
            return self._default()
        if not isinstance(payload, dict):
            return self._default()
        payload.setdefault("muted_until", 0)
        payload.setdefault("paused_strategies", [])
        return payload

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except Exception:  # noqa: BLE001 - never let persistence crash a command
            LOGGER.error("failed to save operator state to %s", self.state_path, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    # --- paused strategies ---------------------------------------------------
    def paused_strategies(self) -> list[str]:
        with self._lock:
            return list(self._state.get("paused_strategies", []))

    def is_paused(self, strategy: str) -> bool:
        with self._lock:
            return strategy in self._state.get("paused_strategies", [])

    def pause(self, strategy: str) -> bool:
        with self._lock:
            paused = self._state.setdefault("paused_strategies", [])
            if strategy not in paused:
                paused.append(strategy)
                self._save()
                return True
            return False

    def resume(self, strategy: str) -> bool:
        with self._lock:
            paused = self._state.get("paused_strategies", [])
            if strategy in paused:
                self._state["paused_strategies"] = [s for s in paused if s != strategy]
                self._save()
                return True
            return False

    # --- mute ----------------------------------------------------------------
    def mute_minutes(self) -> float:
        with self._lock:
            return float(self._state.get("muted_until", 0) or 0)

    def set_mute(self, minutes: float) -> None:
        with self._lock:
            self._state["muted_until"] = minutes
            self._save()
