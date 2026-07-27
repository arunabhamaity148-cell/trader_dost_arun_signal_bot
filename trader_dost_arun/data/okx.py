from __future__ import annotations

import asyncio

from trader_dost_arun.data.base import BasePublicConnector, parse_ts


class OkxConnector(BasePublicConnector):
    venue = "okx"
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    rest_url = "https://www.okx.com"

    def subscription_messages(self) -> list[dict]:
        args = [
            {"channel": "books5", "instId": self.symbol},
            {"channel": "trades", "instId": self.symbol},
            {"channel": "mark-price", "instId": self.symbol},
            {"channel": "funding-rate", "instId": self.symbol},
        ]
        return [{"op": "subscribe", "args": args}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_open_interest(queue), name=f"{self.venue}-{self.symbol}-oi")]

    async def _poll_open_interest(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("open-interest-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            try:
                payload = await self.rest_json("/api/v5/public/open-interest", params={"instType": "SWAP", "instId": self.symbol})
                value = self._parse_open_interest_payload(payload)
                if value is not None:
                    await self.emit_snapshot(queue, open_interest=value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("okx OI poll failed: %s", exc)
            await self._sleep_or_stop(interval)

    def _parse_open_interest_payload(self, payload: dict) -> float | None:
        rows = payload.get("data", [])
        if not rows:
            return None
        row = rows[0]
        value = row.get("oi") or row.get("openInterest")
        return float(value) if value is not None else None

    def parse_message(self, payload: dict):
        arg = payload.get("arg", {})
        channel = arg.get("channel", "")
        data = payload.get("data", [])
        if channel == "books5" and data:
            book = data[0]
            return [self.build_snapshot(parse_ts(int(book.get("ts", 0))), book.get("bids", []), book.get("asks", []))]
        if channel == "trades":
            return [self.build_trade(item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(int(item.get("ts", 0)))) for item in data]
        if channel in {"mark-price", "funding-rate"} and data:
            item = data[0]
            snap = self.build_snapshot(parse_ts(int(item.get("ts", 0))), [], [], float(item.get("markPx", 0.0)), float(item.get("indexPx", 0.0)), float(item.get("fundingRate", 0.0)))
            snap.premium = (snap.mark_price or 0.0) - (snap.index_price or 0.0)
            return [snap]
        return []
