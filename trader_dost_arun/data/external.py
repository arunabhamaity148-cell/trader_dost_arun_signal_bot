from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from trader_dost_arun.newsguard.calendar import EconomicCalendarClient, EconomicCalendarEvent

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExternalContext:
    macro_blocked: bool = False
    sec_blocked: bool = False
    stablecoin_stress: bool = False
    benchmark_returns: dict[str, float] | None = None
    stablecoin_metrics: dict[str, float] | None = None
    macro_events: list[EconomicCalendarEvent] = field(default_factory=list)


class ExternalDataClient:
    def __init__(self, refresh_seconds: int = 180) -> None:
        self.client = httpx.AsyncClient(timeout=15)
        self.refresh_seconds = refresh_seconds
        self.calendar = EconomicCalendarClient(self.client, os.getenv("FRED_API_KEY", ""))
        self._context = ExternalContext()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._refresh_loop(), name="external-context-refresh")
            await self.refresh_once()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.client.aclose()

    def current_context(self) -> ExternalContext:
        return self._context

    async def coingecko_prices(self, ids: list[str]) -> dict[str, Any]:
        response = await self.client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"},
        )
        response.raise_for_status()
        return response.json()

    async def defillama_stablecoins(self) -> dict[str, Any]:
        response = await self.client.get("https://stablecoins.llama.fi/stablecoins?includePrices=true")
        response.raise_for_status()
        return response.json()

    async def sec_feed_recent(self) -> list[datetime]:
        response = await self.client.get("https://www.sec.gov/news/pressreleases.rss")
        response.raise_for_status()
        text = response.text.lower()
        now = datetime.now(timezone.utc)
        return [now] if "crypto" in text else []

    async def refresh_once(self) -> ExternalContext:
        async with self._lock:
            prices = await self.coingecko_prices(["bitcoin", "ethereum", "tether", "usd-coin"])
            stable = await self.defillama_stablecoins()
            macro_events = await self.calendar.upcoming_events()
            sec_events = await self.sec_feed_recent()
            now = datetime.now(timezone.utc)
            macro_blocked = any(abs((event.release_time - now).total_seconds()) <= 20 * 60 for event in macro_events)
            sec_blocked = any(abs((event - now).total_seconds()) <= 20 * 60 for event in sec_events)
            tether_price = prices.get("tether", {}).get("usd", 1.0)
            usdc_price = prices.get("usd-coin", {}).get("usd", 1.0)
            stablecoin_stress = tether_price < 0.997 or usdc_price < 0.997
            benchmark_returns = {
                "BTC": prices.get("bitcoin", {}).get("usd_24h_change", 0.0),
                "ETH": prices.get("ethereum", {}).get("usd_24h_change", 0.0),
            }
            metrics = {
                "tether_usd": tether_price,
                "usdc_usd": usdc_price,
                "stablecoin_count": float(len(stable.get("peggedAssets", []))),
            }
            self._context = ExternalContext(
                macro_blocked=macro_blocked,
                sec_blocked=sec_blocked,
                stablecoin_stress=stablecoin_stress,
                benchmark_returns=benchmark_returns,
                stablecoin_metrics=metrics,
                macro_events=macro_events,
            )
            return self._context

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("external context refresh failed: %s", exc)
            await asyncio.sleep(self.refresh_seconds)
