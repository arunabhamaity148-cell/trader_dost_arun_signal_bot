from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class StateCheckpoint:
    """Periodic JSON snapshot storage for adaptive components.

    Crash-safety: save() writes to a temp file then os.replace()s it into place,
    so a process killed mid-write can never leave a half-written checkpoint.json
    that the next boot would choke on. load_latest() treats a missing/corrupt
    checkpoint as "no prior state" rather than raising, so a damaged file can
    never crash startup (previously json.loads on a truncated file raised inside
    SignalEngine.__init__ and took the whole app down on boot).
    """

    def __init__(self, path: str | Path = "./data/checkpoint.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict[str, Any]) -> None:
        enriched = {"saved_at": datetime.now(timezone.utc).isoformat(), **payload}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(enriched, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self.path)
            # keep a last-known-good backup so a corrupted primary can fall back
            self.path.with_suffix(self.path.suffix + ".bak").write_text(
                self.path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 - a checkpoint write must never crash the hot path
            LOGGER.warning("checkpoint save failed for %s", self.path, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    def load_latest(self) -> dict[str, Any]:
        path = self.path
        if not path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            path = backup if backup.exists() else self.path
            if not path.exists():
                return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - tolerate corrupt/partial checkpoint on boot
            LOGGER.error("checkpoint unreadable/corrupt at %s; starting with empty state", path, exc_info=True)
            return {}
        return payload if isinstance(payload, dict) else {}
