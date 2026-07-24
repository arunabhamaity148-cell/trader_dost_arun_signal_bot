from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx


EXCHANGE_REGISTRY = {
    "binance": [f"binance_addr_{i}" for i in range(1, 11)],
    "okx": [f"okx_addr_{i}" for i in range(1, 9)],
    "bybit": [f"bybit_addr_{i}" for i in range(1, 9)],
    "coinbase": [f"coinbase_addr_{i}" for i in range(1, 7)],
    "kraken": [f"kraken_addr_{i}" for i in range(1, 7)],
    "bitfinex": [f"bitfinex_addr_{i}" for i in range(1, 5)],
    "deribit": [f"deribit_addr_{i}" for i in range(1, 4)],
    "hyperliquid": [f"hyperliquid_addr_{i}" for i in range(1, 4)],
}


@dataclass(slots=True)
class WhaleAlert:
    exchange: str
    net_flow_usd: float
    direction: str
    chain: str


@dataclass(slots=True)
class WhaleTracker:
    client: httpx.AsyncClient | None = None
    cache_ttl_seconds: int = 300
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict)

    async def _get_json(self, key: str, url: str, params: dict[str, Any] | None = None) -> Any:
        now = time.time()
        if key in self._cache and now - self._cache[key][0] < self.cache_ttl_seconds:
            return self._cache[key][1]
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            self._cache[key] = (now, payload)
            return payload
        finally:
            if own_client:
                await client.aclose()

    async def fetch_eth(self) -> list[dict[str, Any]]:
        return await self._get_json("eth", "https://api.etherscan.io/api", {"module": "account", "action": "tokentx"}) or []

    async def fetch_btc(self) -> list[dict[str, Any]]:
        return await self._get_json("btc", "https://mempool.space/api/mempool/recent") or []

    async def fetch_tron(self) -> list[dict[str, Any]]:
        return await self._get_json("tron", "https://apilist.tronscanapi.com/api/transaction") or []

    def net_flow_usd_per_exchange(self, rows: list[dict[str, Any]], chain: str) -> dict[str, float]:
        flows = {name: 0.0 for name in EXCHANGE_REGISTRY}
        for row in rows:
            value = float(row.get("usd", row.get("amount_usd", row.get("value_usd", 0.0))) or 0.0)
            to_addr = str(row.get("to", row.get("toAddress", row.get("receiver", ""))))
            from_addr = str(row.get("from", row.get("ownerAddress", row.get("sender", ""))))
            for exchange, addresses in EXCHANGE_REGISTRY.items():
                if to_addr in addresses:
                    flows[exchange] += value
                if from_addr in addresses:
                    flows[exchange] -= value
        return flows

    async def alerts(self) -> list[WhaleAlert]:
        alerts: list[WhaleAlert] = []
        for chain, fetcher in {"ETH": self.fetch_eth, "BTC": self.fetch_btc, "TRON": self.fetch_tron}.items():
            rows = await fetcher()
            flows = self.net_flow_usd_per_exchange(rows, chain)
            for exchange, value in flows.items():
                if value >= 5_000_000:
                    alerts.append(WhaleAlert(exchange=exchange, net_flow_usd=value, direction="bearish", chain=chain))
                elif value <= -5_000_000:
                    alerts.append(WhaleAlert(exchange=exchange, net_flow_usd=value, direction="bullish", chain=chain))
        return alerts
