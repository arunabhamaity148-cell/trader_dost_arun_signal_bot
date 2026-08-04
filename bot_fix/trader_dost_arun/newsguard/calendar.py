from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Final

import httpx


@dataclass(slots=True)
class EconomicCalendarEvent:
    release_name: str
    release_id: int
    release_date: date
    release_time: datetime
    category: str


class EconomicCalendarClient:
    RELEASE_MATCHERS: Final[dict[str, tuple[str, time]]] = {
        "consumer price index": ("cpi", time(13, 30)),
        "employment situation": ("nfp", time(13, 30)),
        "personal income and outlays": ("pce", time(13, 30)),
        "fomc": ("fomc", time(18, 0)),
        "federal open market committee": ("fomc", time(18, 0)),
    }

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self.client = client
        self.api_key = api_key

    async def upcoming_events(self, days_back: int = 1, days_forward: int = 14) -> list[EconomicCalendarEvent]:
        if not self.api_key:
            return []
        today = datetime.now(timezone.utc).date()
        params = {
            "api_key": self.api_key,
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "realtime_start": (today - timedelta(days=days_back)).isoformat(),
            "realtime_end": (today + timedelta(days=days_forward)).isoformat(),
            "limit": 1000,
            "order_by": "release_date",
            "sort_order": "asc",
        }
        response = await self.client.get("https://api.stlouisfed.org/fred/releases/dates", params=params)
        response.raise_for_status()
        rows = response.json().get("release_dates", [])
        events: list[EconomicCalendarEvent] = []
        for row in rows:
            release_name = str(row.get("release_name", ""))
            lowered = release_name.lower()
            matched = None
            for token, info in self.RELEASE_MATCHERS.items():
                if token in lowered:
                    matched = info
                    break
            if matched is None:
                continue
            category, release_clock = matched
            release_date = date.fromisoformat(row["date"])
            release_time = datetime.combine(release_date, release_clock, tzinfo=timezone.utc)
            events.append(
                EconomicCalendarEvent(
                    release_name=release_name,
                    release_id=int(row.get("release_id", 0)),
                    release_date=release_date,
                    release_time=release_time,
                    category=category,
                )
            )
        return events
