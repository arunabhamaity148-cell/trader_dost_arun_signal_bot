import asyncio
import io
import logging

from trader_dost_arun.ops.alerts import TelegramAlerter
from trader_dost_arun.ops.logging_utils import CooldownDeduper, SafeStreamHandler


class StrictEncodingStream(io.StringIO):
    encoding = "cp1252"

    def write(self, s):
        s.encode(self.encoding, errors="strict")
        return super().write(s)


def test_cooldown_deduper_suppresses_repeated_messages():
    deduper = CooldownDeduper(default_cooldown_seconds=60)
    assert deduper.should_emit("same-key") is True
    assert deduper.should_emit("same-key") is False
    assert deduper.should_emit("other-key") is True


def test_safe_stream_handler_does_not_crash_on_unicode_output():
    stream = StrictEncodingStream()
    handler = SafeStreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("unicode-safe-test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("⚠️ unicode health warning")
    output = stream.getvalue()
    assert "unicode health warning" in output


def test_telegram_send_failure_does_not_raise(monkeypatch, tmp_path):
    class BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("telegram down")

    monkeypatch.setattr("httpx.AsyncClient", BrokenClient)
    alerter = TelegramAlerter("token", "chat", counter_db=tmp_path / "counter.sqlite3")
    asyncio.run(alerter.send("hello"))
