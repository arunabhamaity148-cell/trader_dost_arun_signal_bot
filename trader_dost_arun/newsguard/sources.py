from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from trader_dost_arun.newsguard.models import NewsEvent
from trader_dost_arun.ops.logging_utils import CooldownDeduper

LOGGER = logging.getLogger(__name__)

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


@dataclass(slots=True)
class SourceHealth:
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    last_error: str | None = None
    last_success_at: datetime | None = None
    skipped_due_to_cooldown: int = 0
    retry_budget_remaining: int = 3
    total_failures: int = 0


class BaseNewsSource:
    def __init__(self, name: str, client: httpx.AsyncClient) -> None:
        self.name = name
        self.client = client
        self._failure_deduper = CooldownDeduper(default_cooldown_seconds=300.0)
        self.health = SourceHealth()

    async def fetch(self) -> list[RawNewsItem]:
        raise NotImplementedError

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _cooldown_seconds(self) -> float:
        return min(900.0, 30.0 * (2 ** max(self.health.consecutive_failures - 1, 0)))

    def should_skip(self) -> bool:
        if self.health.cooldown_until is None:
            return False
        now = self._now()
        if now >= self.health.cooldown_until:
            return False
        self.health.skipped_due_to_cooldown += 1
        return True

    def _record_success(self) -> None:
        self.health.last_success_at = self._now()
        self.health.last_error = None
        self.health.consecutive_failures = 0
        self.health.retry_budget_remaining = 3
        self.health.cooldown_until = None

    def _record_failure(self, detail: str) -> None:
        now = self._now()
        self.health.total_failures += 1
        self.health.last_error = detail
        self.health.consecutive_failures += 1
        self.health.retry_budget_remaining = max(0, 3 - self.health.consecutive_failures)
        self.health.cooldown_until = now + timedelta(seconds=self._cooldown_seconds())
        key = f"{self.name}:{detail}"
        if self._failure_deduper.should_emit(key):
            LOGGER.warning("news source %s failed: %s", self.name, detail)

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

    def _looks_like_rss(self, text: str, content_type: str) -> bool:
        preview = text.lstrip()[:400].lower()
        return "xml" in content_type or "<rss" in preview or "<feed" in preview or "<rdf" in preview

    async def fetch(self) -> list[RawNewsItem]:
        if self.should_skip():
            return []
        # Retry transient network failures (timeout/connect/DNS) a couple of
        # times before recording a failure and entering the source's cooldown.
        # Previously a single transient glitch (e.g. gaierror, ConnectTimeout)
        # immediately triggered up to a 15-minute cooldown for that source,
        # even though the same URL fetched fine moments later - these are
        # public RSS endpoints with no auth, so the fix is retrying the
        # request, not credentials.
        max_attempts = 3
        response = None
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.client.get(self.url, follow_redirects=True)
                response.raise_for_status()
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_attempts:
                    await asyncio.sleep(0.5 * attempt)
        if last_exc is not None or response is None:
            self._record_failure(f"rss fetch error: {type(last_exc).__name__}")
            return []
        content_type = response.headers.get("content-type", "").lower()
        text = response.text.strip()
        if not text:
            self._record_failure("rss empty body")
            return []
        if not self._looks_like_rss(text, content_type):
            self._record_failure(f"rss malformed response content-type={content_type or 'unknown'}")
            return []
        try:
            root = ElementTree.fromstring(text)
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"rss parse error: {type(exc).__name__}")
            return []
        items = root.findall(".//item")[:20]
        if not items and root.tag.lower().endswith("feed"):
            items = root.findall(".//{*}entry")[:20]
        results: list[RawNewsItem] = []
        for item in items:
            title = unescape(item.findtext("title", default="") or item.findtext("{*}title", default="")).strip()
            summary = re.sub(r"<[^>]+>", " ", item.findtext("description", default="") or item.findtext("{*}summary", default="")).strip()
            link = item.findtext("link", default="").strip()
            if not link:
                link_node = item.find("{*}link")
                if link_node is not None:
                    link = (link_node.get("href") or "").strip()
            published = item.findtext("pubDate") or item.findtext("published") or item.findtext("updated") or item.findtext("{*}published") or item.findtext("{*}updated")
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc) if published else self._now()
            results.append(RawNewsItem(title=title, summary=summary, url=link, source_type=self.source_type, source_name=self.name, published_at=published_at))
        self._record_success()
        return results


class TelegramChannelSource(BaseNewsSource):
    def __init__(self, name: str, client: httpx.AsyncClient, channel: str) -> None:
        super().__init__(name, client)
        self.channel = channel.lstrip("@")

    async def fetch(self) -> list[RawNewsItem]:
        if self.should_skip():
            return []
        try:
            response = await self.client.get(f"https://t.me/s/{self.channel}", follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"telegram fetch error: {type(exc).__name__}")
            return []
        messages = soup.select("div.tgme_widget_message")[:10]
        results: list[RawNewsItem] = []
        for node in messages:
            text_node = node.select_one("div.tgme_widget_message_text")
            date_node = node.select_one("time")
            if not text_node or not date_node:
                continue
            text = text_node.get_text(" ", strip=True)
            url = node.get("data-post", "")
            published_at = datetime.fromisoformat(date_node.get("datetime").replace("Z", "+00:00")) if date_node.get("datetime") else self._now()
            results.append(RawNewsItem(title=text[:120], summary=text, url=f"https://t.me/{url}" if url else f"https://t.me/{self.channel}", source_type="telegram", source_name=self.name, published_at=published_at))
        self._record_success()
        return results


class EtherscanWhaleSource(BaseNewsSource):
    def __init__(self, name: str, client: httpx.AsyncClient, api_key: str, watched_addresses: list[dict[str, Any]], min_usd_notional: float = 1_000_000) -> None:
        super().__init__(name, client)
        self.api_key = api_key
        self.watched_addresses = watched_addresses
        self.min_usd_notional = min_usd_notional

    async def fetch(self) -> list[RawNewsItem]:
        if not self.api_key or not self.watched_addresses or self.should_skip():
            return []
        items: list[RawNewsItem] = []
        failures = 0
        for watched in self.watched_addresses:
            address = watched.get("address", "")
            symbol = watched.get("symbol", "ETH")
            try:
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
                    follow_redirects=True,
                )
                response.raise_for_status()
                rows = response.json().get("result", [])
            except Exception as exc:  # noqa: BLE001
                failures += 1
                self._record_failure(f"etherscan fetch error address={address[:8]} type={type(exc).__name__}")
                continue
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
        if failures == 0:
            self._record_success()
        return items
