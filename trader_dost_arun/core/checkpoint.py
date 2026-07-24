from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateCheckpoint:
    """Periodic JSON snapshot storage for adaptive components."""

    def __init__(self, path: str | Path = "./data/checkpoint.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict[str, Any]) -> None:
        enriched = {"saved_at": datetime.now(timezone.utc).isoformat(), **payload}
        self.path.write_text(json.dumps(enriched, indent=2, default=str), encoding="utf-8")

    def load_latest(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))
