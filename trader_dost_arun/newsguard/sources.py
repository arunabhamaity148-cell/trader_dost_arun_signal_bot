from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from trader_dost_arun.newsguard.models import NewsEvent

SYMBOL_HINTS = {
    "BTC": ["BTC", "BITCOIN"],
    "ETH": ["ETH", "ETHEREUM"],
    "SOL": ["SOL", "SOLANA"],
    "BNB": ["BNB", "BINANCE COIN"],
    "XRP": ["XRP", "RIPPLE"],
    "DOGE": ["DOGE", "DOGECOIN"],
    "ADA": ["ADA", "CARDANO"],
    "AVAX": ["AVAX", "AVALANCHE"],
    "LINK": ["LINK", "CHAINLINK"],
    "ARB": ["ARB", "ARBITRUM"],
}


@dataclass(slots=True)
class RawNewsItem:
    title: str
    summary: str
    url: str
    source_type: str
    source_name: str
    published_at: datetime
    language: str = "en"


class BaseNewsSource:
    def __init__(self, name: str, client: httpx.AsyncClient) -> None:
        self.name = name
        self.client = client

    async def fetch(self) -> list[RawNewsItem]:
        raise NotImplementedError

    def infer_symbols(self, text: str) -> list[str]:
        normalized = text.upper()
        matches = [symbol for symbol, aliases in SYMBOL_HINTS.items() if any(alias in normalized for alias in aliases)]
        return sorted(set(matches))

    def classify(self, text: str) -> tuple[str, float, float]:
        lowered = text.lower()
        if any(token in lowered for token in ["hack", "exploit", "suspend", "halt", "liquidation"]):
            return "incident", 0.95, -1.0
        if any(token in lowered for token in ["listing", "launch", "upgrade", "partnership"]):
            return "catalyst", 0.6, 0.5
        if any(token in lowered for token in ["fomc", "cpi", "nfp", "inflation", "pce"]):
            return "macro", 0.85, 0.0
        if any(token in lowered for token in ["deposit", "transfer", "whale"]):
            return "whale", 0.75, -0.1
        return "general", 0.35, 0.0

    def normalize(self, item: RawNewsItem) -> NewsEvent:
        text = f"{item.title} {item.summary}".strip()
        category, severity, sentiment = self.classify(text)
        symbols = self.infer_symbols(text)
        entities = list(symbols)
        event_id = hashlib.sha256(f"{item.url}|{item.title}".encode("utf-8")).hexdigest()[:16]
        return NewsEvent(
            event_id=event_id,
            title=item.title,
            summary=item.summary,
            url=item.url,
            source_type=item.source_type,
            source_name=item.source_name,
            category=category,
            severity=severity,
            sentiment=sentiment,
            language=item.language,
            symbols=symbols,
            entities=entities,
            first_seen_at=item.published_at,
            last_seen_at=item.published_at,
        )


class RSSNewsSource(BaseNewsSource):
    def __init__(self, name: str, client: httpx.AsyncClient, url: str, source_type: str = "rss") -> None:
        super().__init__(name, client)
        self.url = url
        self.source_type = source_type

    async def fetch(self) -> list[RawNewsItem]:
        response = await self.client.get(self.url)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        items = root.findall(".//item")[:20]
        results: list[RawNewsItem] = []
        for item in items:
            title = unescape(item.findtext("title", default="")).strip()
            summary = re.sub(r"<[^>]+>", " ", item.findtext("description", default="")).strip()
            link = item.findtext("link", default="").strip()
            published = item.findtext("pubDate") or item.findtext("published") or item.findtext("updated")
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc) if published else datetime.now(timezone.utc)
            results.append(RawNewsItem(title=title, summary=summary, url=link, source_type=self.source_type, source_name=self.name, published_at=published_at))
        return results


class TelegramChannelSource(BaseNewsSource):
    def __init__(self, name: str, client: httpx.AsyncClient, channel: str) -> None:
        super().__init__(name, client)
        self.channel = channel.lstrip("@")

    async def fetch(self) -> list[RawNewsItem]:
        response = await self.client.get(f"https://t.me/s/{self.channel}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        messages = soup.select("div.tgme_widget_message")[:10]
        results: list[RawNewsItem] = []
        for node in messages:
            text_node = node.select_one("div.tgme_widget_message_text")
            date_node = node.select_one("time")
            if not text_node or not date_node:
                continue
            text = text_node.get_text(" ", strip=True)
            url = node.get("data-post", "")
            published_at = datetime.fromisoformat(date_node.get("datetime").replace("Z", "+00:00")) if date_node.get("datetime") else datetime.now(timezone.utc)
            results.append(RawNewsItem(title=text[:120], summary=text, url=f"https://t.me/{url}" if url else f"https://t.me/{self.channel}", source_type="telegram", source_name=self.name, published_at=published_at))
        return results


class EtherscanWhaleSource(BaseNewsSource):
    def __init__(self, name: str, client: httpx.AsyncClient, api_key: str, watched_addresses: list[dict[str, Any]], min_usd_notional: float = 1_000_000) -> None:
        super().__init__(name, client)
        self.api_key = api_key
        self.watched_addresses = watched_addresses
        self.min_usd_notional = min_usd_notional

    async def fetch(self) -> list[RawNewsItem]:
        if not self.api_key or not self.watched_addresses:
            return []
        items: list[RawNewsItem] = []
        for watched in self.watched_addresses:
            address = watched.get("address", "")
            symbol = watched.get("symbol", "ETH")
            response = await self.client.get(
                "https://api.etherscan.io/api",
                params={
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "sort": "desc",
                    "page": 1,
                    "offset": 10,
                    "apikey": self.api_key,
                },
            )
            response.raise_for_status()
            rows = response.json().get("result", [])
            for row in rows:
                value_eth = float(row.get("value", 0.0)) / 1e18
                if value_eth * float(watched.get("reference_price", 0.0) or 0.0) < self.min_usd_notional:
                    continue
                txhash = row.get("hash", "")
                counterparty = row.get("from", "")
                title = f"Large exchange-bound transfer to {watched.get('label', address)}"
                summary = f"{value_eth:.2f} {symbol} moved from {counterparty} into watched exchange address {address}."
                published_at = datetime.fromtimestamp(int(row.get("timeStamp", 0)), tz=timezone.utc)
                items.append(RawNewsItem(title=title, summary=summary, url=f"https://etherscan.io/tx/{txhash}", source_type="onchain", source_name=self.name, published_at=published_at))
        return items
