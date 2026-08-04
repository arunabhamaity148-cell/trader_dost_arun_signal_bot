from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app import TradingApplication
from trader_dost_arun.core.config import load_settings


async def main() -> None:
    root = Path(__file__).resolve().parent
    settings = load_settings(root)
    settings.config["watchlist"] = {
        "binance": ["BTCUSDT"],
        "bybit": ["BTCUSDT"],
        "okx": ["BTC-USDT-SWAP"],
    }
    settings.config["ops"]["health_port"] = 18086
    settings.config["ops"]["health_refresh_seconds"] = 0.5
    settings.config["system"]["min_snapshots_before_signals"] = 5
    app = TradingApplication(root, settings=settings)
    try:
        await app.start()
        await asyncio.sleep(20)
    finally:
        await app.stop()
    print(json.dumps(app.runtime_snapshot(), default=str))


if __name__ == "__main__":
    asyncio.run(main())
