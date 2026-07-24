from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload)


def configure_logging(project_root: Path) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    text_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(text_fmt)
    text_handler = RotatingFileHandler(log_dir / "signal_bot.log", maxBytes=5_000_000, backupCount=5)
    text_handler.setFormatter(text_fmt)
    json_handler = RotatingFileHandler(log_dir / "structured.jsonl", maxBytes=5_000_000, backupCount=5)
    json_handler.setFormatter(JsonFormatter())
    root.addHandler(console)
    root.addHandler(text_handler)
    root.addHandler(json_handler)
