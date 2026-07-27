from __future__ import annotations

import json
import logging
import re
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

TELEGRAM_BOT_URL_PATTERN = re.compile(r"(https?://api\.telegram\.org/bot)([^/\s]+)(/[^\s'\"]*)", re.IGNORECASE)
TELEGRAM_TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{10,}\b")
QUERY_SECRET_PATTERN = re.compile(r"([?&](?:api_)?key=|[?&](?:access_)?token=|[?&]secret=)([^&#\s]+)", re.IGNORECASE)
HEADER_SECRET_PATTERN = re.compile(r"((?:authorization|x-api-key|api-key|api_key)['\"]?\s*[:=]\s*['\"]?)([^'\",\s]+)", re.IGNORECASE)
BEARER_SECRET_PATTERN = re.compile(r"(Bearer\s+)([A-Za-z0-9._~+\-/=]+)", re.IGNORECASE)


def redact_secrets(value: object) -> str:
    text = str(value)
    text = TELEGRAM_BOT_URL_PATTERN.sub(r"\1<REDACTED>\3", text)
    text = TELEGRAM_TOKEN_PATTERN.sub("<REDACTED_TELEGRAM_TOKEN>", text)
    text = QUERY_SECRET_PATTERN.sub(r"\1<REDACTED>", text)
    text = HEADER_SECRET_PATTERN.sub(r"\1<REDACTED>", text)
    text = BEARER_SECRET_PATTERN.sub(r"\1<REDACTED>", text)
    return text


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001
            rendered = str(record.msg)
        record.msg = redact_secrets(rendered)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        return json.dumps(payload, ensure_ascii=False)


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe = (msg + self.terminator).encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
                stream.write(safe)
            self.flush()
        except Exception:
            self.handleError(record)


class CooldownDeduper:
    def __init__(self, default_cooldown_seconds: float = 60.0) -> None:
        self.default_cooldown_seconds = default_cooldown_seconds
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_emit(self, key: str, cooldown_seconds: float | None = None) -> bool:
        ttl = self.default_cooldown_seconds if cooldown_seconds is None else cooldown_seconds
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(key)
            if last is not None and now - last < ttl:
                return False
            self._last_seen[key] = now
            return True

    def clear(self) -> None:
        with self._lock:
            self._last_seen.clear()


def configure_logging(project_root: Path) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    text_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    redaction_filter = SecretRedactionFilter()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    logging.raiseExceptions = False

    console = SafeStreamHandler()
    console.setFormatter(text_fmt)
    console.addFilter(redaction_filter)

    text_handler = RotatingFileHandler(log_dir / "signal_bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    text_handler.setFormatter(text_fmt)
    text_handler.addFilter(redaction_filter)

    json_handler = RotatingFileHandler(log_dir / "structured.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    json_handler.setFormatter(JsonFormatter())
    json_handler.addFilter(redaction_filter)

    root.addFilter(redaction_filter)
    root.addHandler(console)
    root.addHandler(text_handler)
    root.addHandler(json_handler)

    for noisy_logger in ("httpx", "httpcore", "websockets", "urllib3"):
        logger = logging.getLogger(noisy_logger)
        logger.setLevel(logging.WARNING)
        logger.propagate = True
        logger.filters.clear()
        logger.addFilter(redaction_filter)
