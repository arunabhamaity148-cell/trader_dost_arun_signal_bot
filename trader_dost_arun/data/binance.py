from __future__ import annotations

import asyncio

from trader_dost_arun.data.base import BasePublicConnector, parse_ts


class BinanceConnector(BasePublicConnector):
    venue = "binance"
    ws_url = "wss://fstream.binance.com/stream"
    rest_url = "https://fapi.binance.com"

    def subscription_messages(self) -> list[dict]:
        s = self.symbol.lower().replace("/", "")
        streams = [f"{s}@depth20@100ms", f"{s}@trade", f"{s}@markPrice@1s", f"{s}@forceOrder"]
        return [{"method": "SUBSCRIBE", "params": streams, "id": 1}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_open_interest(queue), name=f"{self.venue}-{self.symbol}-oi")]

    async def _poll_open_interest(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("open-interest-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            try:
                payload = await self.rest_json("/fapi/v1/openInterest", params={"symbol": self.symbol})
                value = self._parse_open_interest_payload(payload)
                if value is not None:
                    await self.emit_snapshot(queue, open_interest=value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("binance OI poll failed: %s", exc)
            await asyncio.sleep(interval)

    def _parse_open_interest_payload(self, payload: dict) -> float | None:
        value = payload.get("openInterest")
        return float(value) if value is not None else None

    def parse_message(self, payload: dict):
        data = payload.get("data", payload)
        stream = payload.get("stream", "")
        if "depth" in stream and data.get("b") and data.get("a"):
            event_time = parse_ts(data.get("E"))
            return [self.build_snapshot(event_time, data["b"], data["a"])]
        if "trade" in stream and data.get("p"):
            return [self.build_trade(data["p"], data["q"], "sell" if data.get("m") else "buy", parse_ts(data.get("T")))]
        if "markPrice" in stream:
            snap = self.build_snapshot(parse_ts(data.get("E")), [], [], float(data.get("p", 0.0)), float(data.get("i", 0.0)), float(data.get("r", 0.0)))
            snap.premium = (snap.mark_price or 0.0) - (snap.index_price or 0.0)
            return [snap]
        if "forceOrder" in stream and data.get("o"):
            order = data["o"]
            return [self.build_liquidation(order.get("p", 0.0), order.get("q", 0.0), order.get("S", "buy"), parse_ts(order.get("T")))]
        return []
