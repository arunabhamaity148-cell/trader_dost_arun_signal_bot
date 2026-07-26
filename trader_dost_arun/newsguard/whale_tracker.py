from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
import logging

import httpx

LOGGER = logging.getLogger(__name__)

SOLANA_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

EXCHANGE_REGISTRY = {
    "binance": [
        *[f"binance_addr_{i}" for i in range(1, 11)],
        "binance_sol_addr_1",
        "binance_sol_addr_2",
    ],
    "okx": [
        *[f"okx_addr_{i}" for i in range(1, 9)],
        "okx_sol_addr_1",
    ],
    "bybit": [
        *[f"bybit_addr_{i}" for i in range(1, 9)],
        "bybit_sol_addr_1",
    ],
    "coinbase": [
        *[f"coinbase_addr_{i}" for i in range(1, 7)],
        "coinbase_sol_addr_1",
    ],
    "kraken": [
        *[f"kraken_addr_{i}" for i in range(1, 7)],
        "kraken_sol_addr_1",
    ],
    "bitfinex": [
        *[f"bitfinex_addr_{i}" for i in range(1, 5)],
        "bitfinex_sol_addr_1",
    ],
    "deribit": [
        *[f"deribit_addr_{i}" for i in range(1, 4)],
        "deribit_sol_addr_1",
    ],
    "hyperliquid": [
        *[f"hyperliquid_addr_{i}" for i in range(1, 4)],
        "hyperliquid_sol_addr_1",
    ],
}


@dataclass(slots=True)
class WhaleAlert:
    exchange: str
    net_flow_usd: float
    direction: str
    chain: str


@dataclass
class WhaleTracker:
    client: httpx.AsyncClient | None = None
    cache_ttl_seconds: int = 300
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict)

    async def _get_json(self, key: str, url: str, params: dict[str, Any] | None = None) -> Any:
        now = time.time()
        if key in self._cache and now - self._cache[key][0] < self.cache_ttl_seconds:
            return self._cache[key][1]
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15, follow_redirects=True)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            self._cache[key] = (now, payload)
            return payload
        finally:
            if own_client:
                await client.aclose()

    async def _post_json(self, key: str, url: str, payload: dict[str, Any]) -> Any:
        now = time.time()
        if key in self._cache and now - self._cache[key][0] < self.cache_ttl_seconds:
            return self._cache[key][1]
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15, follow_redirects=True)
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            parsed = response.json()
            self._cache[key] = (now, parsed)
            return parsed
        finally:
            if own_client:
                await client.aclose()

    async def fetch_eth(self) -> list[dict[str, Any]]:
        return await self._get_json("eth", "https://api.etherscan.io/api", {"module": "account", "action": "tokentx"}) or []

    async def fetch_btc(self) -> list[dict[str, Any]]:
        return await self._get_json("btc", "https://mempool.space/api/mempool/recent") or []

    async def fetch_tron(self) -> list[dict[str, Any]]:
        return await self._get_json("tron", "https://apilist.tronscanapi.com/api/transaction") or []

    async def fetch_solana(self) -> list[dict[str, Any]]:
        endpoint = "https://api.mainnet-beta.solana.com"
        signatures_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [SOLANA_USDC_MINT, {"limit": 15, "commitment": "confirmed"}],
        }
        signatures_response = await self._post_json("solana.signatures", endpoint, signatures_payload)
        signatures = signatures_response.get("result", []) if isinstance(signatures_response, dict) else []
        rows: list[dict[str, Any]] = []
        for item in signatures:
            signature = item.get("signature")
            if not signature:
                continue
            tx_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
            }
            tx_response = await self._post_json(f"solana.tx.{signature}", endpoint, tx_payload)
            result = tx_response.get("result") if isinstance(tx_response, dict) else None
            meta = result.get("meta", {}) if isinstance(result, dict) else {}
            pre = meta.get("preTokenBalances", []) or []
            post = meta.get("postTokenBalances", []) or []
            pre_balances = self._solana_owner_balances(pre)
            post_balances = self._solana_owner_balances(post)
            owners = set(pre_balances) | set(post_balances)
            if not owners:
                continue
            deltas = {owner: post_balances.get(owner, 0.0) - pre_balances.get(owner, 0.0) for owner in owners}
            sender = min(deltas.items(), key=lambda item: item[1])
            receiver = max(deltas.items(), key=lambda item: item[1])
            amount = min(abs(sender[1]), max(receiver[1], 0.0))
            if amount <= 0:
                continue
            rows.append({
                "usd": amount,
                "from": sender[0],
                "to": receiver[0],
                "signature": signature,
                "chain": "SOL",
            })
        return rows

    def _solana_owner_balances(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        balances: dict[str, float] = {}
        for row in rows:
            if row.get("mint") != SOLANA_USDC_MINT:
                continue
            owner = str(row.get("owner") or row.get("accountIndex") or "").lower()
            ui_amount = row.get("uiTokenAmount", {}) if isinstance(row.get("uiTokenAmount"), dict) else {}
            amount = ui_amount.get("uiAmount")
            if amount is None:
                raw_amount = ui_amount.get("amount")
                decimals = int(ui_amount.get("decimals", 6) or 6)
                amount = float(raw_amount or 0.0) / (10**decimals)
            balances[owner] = float(amount or 0.0)
        return balances

    def net_flow_usd_per_exchange(self, rows: list[dict[str, Any]], chain: str) -> dict[str, float]:
        del chain
        registry = {exchange: {addr.lower() for addr in addresses} for exchange, addresses in EXCHANGE_REGISTRY.items()}
        flows = {name: 0.0 for name in EXCHANGE_REGISTRY}
        for row in rows:
            value = float(row.get("usd", row.get("amount_usd", row.get("value_usd", 0.0))) or 0.0)
            to_addr = str(row.get("to", row.get("toAddress", row.get("receiver", "")))).lower()
            from_addr = str(row.get("from", row.get("ownerAddress", row.get("sender", "")))).lower()
            for exchange, addresses in registry.items():
                if to_addr in addresses:
                    flows[exchange] += value
                if from_addr in addresses:
                    flows[exchange] -= value
        return flows

    async def alerts(self) -> list[WhaleAlert]:
        alerts: list[WhaleAlert] = []
        for chain, fetcher in {
            "ETH": self.fetch_eth,
            "BTC": self.fetch_btc,
            "TRON": self.fetch_tron,
            "SOL": self.fetch_solana,
        }.items():
            try:
                rows = await fetcher()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("whale tracker fetch failed for %s: %s", chain, exc)
                continue
            flows = self.net_flow_usd_per_exchange(rows, chain)
            for exchange, value in flows.items():
                if value >= 5_000_000:
                    alerts.append(WhaleAlert(exchange=exchange, net_flow_usd=value, direction="bearish", chain=chain))
                elif value <= -5_000_000:
                    alerts.append(WhaleAlert(exchange=exchange, net_flow_usd=value, direction="bullish", chain=chain))
        return alerts
