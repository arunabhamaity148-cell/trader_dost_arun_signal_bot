from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app import TradingApplication
from trader_dost_arun.core.config import load_settings

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "soak_15m_runtime.json"


async def main() -> int:
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    settings = load_settings(ROOT)
    settings.config["ops"]["health_port"] = 18089
    settings.config["ops"]["health_refresh_seconds"] = 1.0
    settings.config["system"]["min_snapshots_before_signals"] = 5
    app = TradingApplication(ROOT, settings=settings)
    checkpoints = {}
    try:
        await app.start()
        for minutes, seconds in ((5, 300), (10, 300), (15, 300)):
            await asyncio.sleep(seconds)
            checkpoints[f"minute_{minutes}"] = app.runtime_snapshot()
        final_snapshot = app.runtime_snapshot()
    finally:
        await app.stop()
    payload = {
        "checkpoints": checkpoints,
        "final": final_snapshot,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
