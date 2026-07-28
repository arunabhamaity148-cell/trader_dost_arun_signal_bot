from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from trader_dost_arun.newsguard.calendar import EconomicCalendarClient, EconomicCalendarEvent

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


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
        self._consecutive_failures = 0
        self._cooldown_until: datetime | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._refresh_loop(), name="external-context-refresh")
            try:
                await self.refresh_once()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("external context bootstrap degraded: error_type=%s", type(exc).__name__)

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

    async def _safe_component_call(
        self,
        name: str,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: T,
        **kwargs: Any,
    ) -> T:
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("external context component failed: component=%s error_type=%s", name, type(exc).__name__)
            return fallback

    async def refresh_once(self) -> ExternalContext:
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._cooldown_until is not None and now < self._cooldown_until:
                return self._context
            prices = await self._safe_component_call(
                "coingecko_prices",
                self.coingecko_prices,
                ["bitcoin", "ethereum", "tether", "usd-coin"],
                fallback={},
            )
            stable = await self._safe_component_call("defillama_stablecoins", self.defillama_stablecoins, fallback={})
            macro_events = await self._safe_component_call("economic_calendar", self.calendar.upcoming_events, fallback=[])
            sec_events = await self._safe_component_call("sec_feed_recent", self.sec_feed_recent, fallback=[])
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
            if prices or stable or macro_events or sec_events:
                self._consecutive_failures = 0
                self._cooldown_until = None
            else:
                self._consecutive_failures += 1
                backoff = min(max(self.refresh_seconds, 5), 300) * min(self._consecutive_failures, 4)
                self._cooldown_until = now + timedelta(seconds=backoff)
            return self._context

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                backoff = min(max(self.refresh_seconds, 5), 300) * min(self._consecutive_failures, 4)
                self._cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                LOGGER.warning("external context refresh failed: error_type=%s cooldown_seconds=%s", type(exc).__name__, int(backoff))
            await asyncio.sleep(self.refresh_seconds)
