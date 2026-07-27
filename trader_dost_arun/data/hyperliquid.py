from __future__ import annotations

import asyncio
from typing import Any

from trader_dost_arun.data.base import BasePublicConnector, parse_ts


class HyperliquidConnector(BasePublicConnector):
    venue = "hyperliquid"
    ws_url = "wss://api.hyperliquid.xyz/ws"
    rest_url = "https://api.hyperliquid.xyz"

    def subscription_messages(self) -> list[dict]:
        coin = self.symbol.split("-")[0]
        return [
            {"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}},
            {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}},
            {"method": "subscribe", "subscription": {"type": "allMids"}},
            {"method": "subscribe", "subscription": {"type": "liquidations", "coin": coin}},
        ]

    def supplemental_streams(self, queue: asyncio.Queue) -> list[asyncio.Task]:
        return [asyncio.create_task(self._poll_asset_context(queue), name=f"{self.venue}-{self.symbol}-assetctx")]

    async def _poll_asset_context(self, queue: asyncio.Queue) -> None:
        interval = int(self.config.get("open_interest_poll_seconds", 15))
        await self.stagger_start("asset-context-poll", max_delay_seconds=min(float(interval), 5.0))
        while not self._stop.is_set():
            try:
                payload = await self.rest_post_json("/info", {"type": "metaAndAssetCtxs"})
                ctx = self._parse_asset_context(payload)
                if ctx:
                    await self.emit_snapshot(
                        queue,
                        mark_price=ctx.get("mark_price"),
                        index_price=ctx.get("index_price"),
                        funding_rate=ctx.get("funding_rate"),
                        open_interest=ctx.get("open_interest"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("hyperliquid asset context poll failed: %s", exc)
            await self._sleep_or_stop(interval)

    def _parse_asset_context(self, payload: list[Any] | dict[str, Any]) -> dict[str, float] | None:
        coin = self.symbol.split("-")[0]
        if not isinstance(payload, list) or len(payload) < 2:
            return None
        universe = payload[0].get("universe", []) if isinstance(payload[0], dict) else []
        contexts = payload[1] if isinstance(payload[1], list) else []
        for index, item in enumerate(universe):
            name = item.get("name") or item.get("coin")
            if name != coin or index >= len(contexts):
                continue
            ctx = contexts[index]
            mark = float(ctx.get("markPx") or 0.0)
            oracle = float(ctx.get("oraclePx") or mark)
            return {
                "mark_price": mark,
                "index_price": oracle,
                "funding_rate": float(ctx.get("funding") or 0.0),
                "open_interest": float(ctx.get("openInterest") or 0.0),
            }
        return None

    def parse_message(self, payload: dict):
        channel = payload.get("channel", "")
        data = payload.get("data", {})
        if channel == "l2Book" and data:
            levels = data.get("levels", [[], []])
            bids = levels[0] if len(levels) > 0 else []
            asks = levels[1] if len(levels) > 1 else []
            return [self.build_snapshot(parse_ts(data.get("time")), bids, asks)]
        if channel == "trades":
            return [self.build_trade(item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(item.get("time"))) for item in data]
        if channel == "allMids" and data:
            coin = self.symbol.split("-")[0]
            px = float(data.get("mids", {}).get(coin, 0.0))
            return [self.build_snapshot(parse_ts(payload.get("time")), [], [], px, px)]
        if channel == "liquidations":
            return [self.build_liquidation(item.get("px", 0.0), item.get("sz", 0.0), item.get("side", "buy"), parse_ts(item.get("time"))) for item in data]
        return []
