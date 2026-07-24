from __future__ import annotations

from trader_dost_arun.data.base import BasePublicConnector, parse_ts


class BybitConnector(BasePublicConnector):
    venue = "bybit"
    ws_url = "wss://stream.bybit.com/v5/public/linear"
    rest_url = "https://api.bybit.com"

    def subscription_messages(self) -> list[dict]:
        return [{"op": "subscribe", "args": [f"orderbook.50.{self.symbol}", f"publicTrade.{self.symbol}", f"tickers.{self.symbol}"]}]

    def parse_message(self, payload: dict):
        topic = payload.get("topic", "")
        data = payload.get("data", {})
        if topic.startswith("orderbook") and data:
            return [self.build_snapshot(parse_ts(payload.get("ts")), data.get("b", []), data.get("a", []))]
        if topic.startswith("publicTrade"):
            return [self.build_trade(item.get("p", 0.0), item.get("v", 0.0), item.get("S", "buy"), parse_ts(item.get("T"))) for item in data]
        if topic.startswith("tickers") and data:
            snap = self.build_snapshot(parse_ts(payload.get("ts")), [], [], float(data.get("markPrice", 0.0)), float(data.get("indexPrice", 0.0)), float(data.get("fundingRate", 0.0)), float(data.get("openInterest", 0.0)))
            snap.premium = snap.mark_price - snap.index_price
            return [snap]
        return []
