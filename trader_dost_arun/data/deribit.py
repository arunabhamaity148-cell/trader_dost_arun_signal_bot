from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from trader_dost_arun.data.base import BasePublicConnector, parse_ts


class DeribitConnector(BasePublicConnector):
    venue = "deribit"
    ws_url = "wss://www.deribit.com/ws/api/v2"
    rest_url = "https://www.deribit.com/api/v2"

    def subscription_messages(self) -> list[dict]:
        channels = [f"book.{self.symbol}.100ms", f"trades.{self.symbol}.100ms", f"ticker.{self.symbol}.100ms"]
        return [{"jsonrpc": "2.0", "id": 42, "method": "public/subscribe", "params": {"channels": channels}}]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_option_metrics(queue), name=f"{self.venue}-{self.symbol}-options")]

    async def _poll_option_metrics(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("options_poll_seconds", 30))
        currency = self.symbol.split("-")[0]
        await self.stagger_start("option-metrics-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            try:
                payload = await self.rest_json("/public/get_book_summary_by_currency", params={"currency": currency, "kind": "option"})
                metrics = self._compute_option_metrics(payload.get("result", []))
                if metrics:
                    await self.emit_snapshot(queue, option_atm_iv=metrics["atm_iv"], option_put_call_skew=metrics["put_call_skew"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("deribit options poll failed: %s", exc)
            await self._sleep_or_stop(interval)

    def _compute_option_metrics(self, rows: list[dict]) -> dict[str, float] | None:
        best_by_expiry: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in rows:
            instrument = row.get("instrument_name", "")
            parts = instrument.split("-")
            if len(parts) < 4:
                continue
            expiry = parts[1]
            strike = float(parts[2])
            option_type = parts[3]
            underlying = float(row.get("underlying_price") or 0.0)
            mark_iv = row.get("mark_iv")
            if not underlying or mark_iv is None:
                continue
            distance = abs(strike - underlying)
            existing = best_by_expiry[expiry].get(option_type)
            if existing is None or distance < existing["distance"]:
                best_by_expiry[expiry][option_type] = {"distance": distance, "mark_iv": float(mark_iv)}
        if not best_by_expiry:
            return None
        expiry = min(best_by_expiry, key=lambda key: datetime.strptime(key, "%d%b%y"))
        selected = best_by_expiry[expiry]
        call_iv = selected.get("C", {}).get("mark_iv")
        put_iv = selected.get("P", {}).get("mark_iv")
        ivs = [iv for iv in [call_iv, put_iv] if iv is not None]
        if not ivs:
            return None
        atm_iv = sum(ivs) / len(ivs)
        skew = (put_iv or atm_iv) - (call_iv or atm_iv)
        return {"atm_iv": atm_iv, "put_call_skew": skew}

    def parse_message(self, payload: dict):
        params = payload.get("params", {})
        channel = params.get("channel", "")
        data = params.get("data", {})
        if channel.startswith("book"):
            return [self.build_snapshot(parse_ts(data.get("timestamp")), data.get("bids", []), data.get("asks", []), data.get("mark_price"), data.get("index_price"), data.get("current_funding", 0.0), data.get("open_interest", 0.0), (data.get("mark_price", 0.0) - data.get("index_price", 0.0)))]
        if channel.startswith("trades"):
            return [self.build_trade(item.get("price", 0.0), item.get("amount", 0.0), item.get("direction", "buy"), parse_ts(item.get("timestamp"))) for item in data]
        if channel.startswith("ticker") and data:
            snap = self.build_snapshot(parse_ts(data.get("timestamp")), [], [], data.get("mark_price", 0.0), data.get("index_price", 0.0), data.get("current_funding", 0.0), data.get("open_interest", 0.0), data.get("mark_price", 0.0) - data.get("index_price", 0.0))
            return [snap]
        return []
