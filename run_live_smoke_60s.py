from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app import TradingApplication
from trader_dost_arun.core.config import load_settings

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "smoke_60s_runtime.json"


async def main() -> int:
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    settings = load_settings(ROOT)
    settings.config["ops"]["health_port"] = 18087
    settings.config["ops"]["health_refresh_seconds"] = 1.0
    settings.config["system"]["min_snapshots_before_signals"] = 5
    app = TradingApplication(ROOT, settings=settings)
    try:
        await app.start()
        await asyncio.sleep(60)
        snapshot = app.runtime_snapshot()
    finally:
        await app.stop()
    OUTPUT_JSON.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    print(json.dumps(snapshot, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
