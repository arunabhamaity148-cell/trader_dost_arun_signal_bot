from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
try:
    from langdetect import detect
except Exception:  # noqa: BLE001
    def detect(_: str) -> str:
        return "en"

from trader_dost_arun.core.models import FeatureSet
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.core.symbols import normalize_instrument
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.newsguard.calendar import EconomicCalendarClient
from trader_dost_arun.newsguard.db import EventReplayStore
from trader_dost_arun.newsguard.embeddings import SemanticTextEmbedder
from trader_dost_arun.newsguard.models import ImpactAssessment, NewsEvent, ObservedImpact
from trader_dost_arun.newsguard.sources import EtherscanWhaleSource, RSSNewsSource, TelegramChannelSource

LOGGER = logging.getLogger(__name__)


class NewsGuard:
    HALF_LIFE_MINUTES = {
        "incident": 240,
        "macro": 120,
        "whale": 90,
        "catalyst": 180,
        "general": 60,
    }

    PROPAGATION = {
        "BTC": {"ETH": 0.7, "SOL": 0.5},
        "ETH": {"BTC": 0.6, "ARB": 0.7, "LINK": 0.5},
        "SOL": {"BTC": 0.4, "ETH": 0.5},
    }

    def __init__(self, config: dict, external_client: httpx.AsyncClient | None = None) -> None:
        self.config = config.get("news_guard", {})
        self.http = external_client or httpx.AsyncClient(timeout=15)
        self.calendar = EconomicCalendarClient(self.http, self.config.get("fred_api_key", ""))
        self.embedder = SemanticTextEmbedder()
        self.store = EventReplayStore(Path(self.config.get("replay_db_path", "./data/news_guard_replay.sqlite3")))
        self.events: dict[str, NewsEvent] = {}
        self.source_scores: dict[str, float] = defaultdict(lambda: 1.0)
        self._task: asyncio.Task | None = None
        self._own_client = external_client is None
        self.sources = self._build_sources()

    def _build_sources(self) -> list:
        sources = []
        for source in self.config.get("rss_sources", []):
            sources.append(RSSNewsSource(source.get("name", "rss"), self.http, source["url"], source.get("source_type", "rss")))
        for source in self.config.get("x_sources", []):
            sources.append(RSSNewsSource(source.get("name", "x"), self.http, source["rss_url"], "x"))
        for source in self.config.get("telegram_sources", []):
            sources.append(TelegramChannelSource(source.get("name", source["channel"]), self.http, source["channel"]))
        whale_cfg = self.config.get("whale_monitor", {})
        if whale_cfg:
            sources.append(
                EtherscanWhaleSource(
                    whale_cfg.get("name", "etherscan_whales"),
                    self.http,
                    whale_cfg.get("api_key", ""),
                    whale_cfg.get("watched_addresses", []),
                    float(whale_cfg.get("min_usd_notional", 1_000_000)),
                )
            )
        return sources

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._refresh_loop(), name="news-guard-refresh")
            await self.refresh_once()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._own_client:
            await self.http.aclose()

    async def _refresh_loop(self) -> None:
        interval = int(self.config.get("refresh_seconds", 120))
        while True:
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("news guard refresh failed: %s", exc)
            await asyncio.sleep(interval)


    async def _normalize_source_item(self, source, item) -> NewsEvent:
        text = f"{item.title} {item.summary}".strip()
        try:
            detected_lang = detect(text) if text else "en"
        except Exception:  # noqa: BLE001
            detected_lang = "en"
        if detected_lang != "en":
            translated = await self._translate_to_english(text)
            if translated:
                item.title = translated[:120]
                item.summary = translated
                item.language = detected_lang
        return source.normalize(item)

    async def _translate_to_english(self, text: str) -> str:
        response = await self.http.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text},
        )
        response.raise_for_status()
        payload = response.json()
        if not payload or not payload[0]:
            return text
        return "".join(part[0] for part in payload[0] if part and part[0])

    async def refresh_once(self) -> None:
        calendar_events = await self.calendar.upcoming_events() if self.config.get("fred_api_key") else []
        for macro_event in calendar_events:
            event = NewsEvent(
                event_id=f"macro-{macro_event.release_id}-{macro_event.release_date.isoformat()}",
                title=macro_event.release_name,
                summary=f"Scheduled {macro_event.category.upper()} release",
                url="https://fred.stlouisfed.org/releases/calendar",
                source_type="macro_calendar",
                source_name="fred",
                category="macro",
                severity=0.9,
                sentiment=0.0,
                language="en",
                symbols=["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "ARB"],
                entities=[macro_event.category.upper()],
                first_seen_at=macro_event.release_time,
                last_seen_at=macro_event.release_time,
            )
            self._merge_event(event)
        for source in self.sources:
            try:
                items = await source.fetch()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("news source %s failed: %s", getattr(source, "name", "unknown"), exc)
                continue
            for item in items:
                event = await self._normalize_source_item(source, item)
                self._merge_event(event)
        for event in self.events.values():
            self._advance_lifecycle(event)
            self.store.upsert_event(event)

    def _merge_event(self, incoming: NewsEvent) -> None:
        for existing in self.events.values():
            if existing.url and existing.url == incoming.url:
                self._combine(existing, incoming)
                return
            if not set(existing.symbols).intersection(incoming.symbols):
                continue
            similarity = self.embedder.similarity(
                f"{existing.title} {existing.summary}",
                f"{incoming.title} {incoming.summary}",
            )
            if similarity >= float(self.config.get("semantic_similarity_threshold", 0.72)):
                self._combine(existing, incoming)
                return
        incoming.consensus_score = self._consensus_score(incoming)
        self.events[incoming.event_id] = incoming

    def _combine(self, existing: NewsEvent, incoming: NewsEvent) -> None:
        existing.last_seen_at = max(existing.last_seen_at, incoming.last_seen_at)
        existing.mention_count += 1
        existing.symbols = sorted(set(existing.symbols + incoming.symbols))
        existing.entities = sorted(set(existing.entities + incoming.entities))
        existing.source_reliability = max(0.3, (existing.source_reliability + self.source_scores[incoming.source_name]) / 2)
        existing.consensus_score = self._consensus_score(existing)
        if incoming.severity > existing.severity:
            existing.severity = incoming.severity
            existing.summary = incoming.summary
            existing.title = incoming.title

    def _consensus_score(self, event: NewsEvent) -> float:
        diversity = 1.0 + len(set(event.entities or event.symbols)) * 0.05
        mention_boost = min(event.mention_count, 5) * 0.1
        return min(2.0, diversity + mention_boost + self.source_scores[event.source_name] * 0.25)

    def _advance_lifecycle(self, event: NewsEvent) -> None:
        age_minutes = max((datetime.now(timezone.utc) - event.first_seen_at).total_seconds() / 60, 0)
        if age_minutes < 5:
            event.lifecycle = "detected"
        elif age_minutes < 15:
            event.lifecycle = "confirmed"
        elif age_minutes < 45:
            event.lifecycle = "escalating"
        elif age_minutes < 120:
            event.lifecycle = "peak"
        elif age_minutes < 240:
            event.lifecycle = "decay"
        elif age_minutes < 360:
            event.lifecycle = "resolved"
        else:
            event.lifecycle = "expired"

    def _impact_decay(self, event: NewsEvent) -> float:
        half_life = self.HALF_LIFE_MINUTES.get(event.category, 60)
        age_minutes = max((datetime.now(timezone.utc) - event.first_seen_at).total_seconds() / 60, 0)
        return 0.5 ** (age_minutes / half_life)

    def _symbol_matches(self, event: NewsEvent, symbol: str) -> bool:
        identity = normalize_instrument("", symbol)
        base_symbol = identity.base_asset
        if base_symbol in event.symbols or symbol in event.symbols:
            return True
        for anchor, related in self.PROPAGATION.items():
            if anchor in event.symbols and base_symbol in related:
                return True
        return False

    def observe_market(self, symbol: str, state: MarketStateStore) -> None:
        now = datetime.now(timezone.utc)
        for event in self.events.values():
            if not self._symbol_matches(event, symbol):
                continue
            if event.lifecycle not in {"peak", "resolved", "decay"}:
                continue
            if event.observed_impact.measured_at and now - event.observed_impact.measured_at < timedelta(minutes=5):
                continue
            matching_views = [view for venue, view in state.peer_views(symbol).items() if view.closes]
            if not matching_views:
                continue
            view = matching_views[0]
            if len(view.closes) < 6:
                continue
            midpoint = len(view.closes) // 2
            pre = view.closes[max(0, midpoint - 3):midpoint]
            post = view.closes[midpoint: midpoint + 3]
            if not pre or not post:
                continue
            pre_price = sum(pre) / len(pre)
            post_price = sum(post) / len(post)
            pre_oi = sum(view.open_interests[max(0, midpoint - 3):midpoint] or [0.0]) / max(len(view.open_interests[max(0, midpoint - 3):midpoint] or [0.0]), 1)
            post_oi = sum(view.open_interests[midpoint: midpoint + 3] or [0.0]) / max(len(view.open_interests[midpoint: midpoint + 3] or [0.0]), 1)
            pre_funding = sum(view.funding_rates[max(0, midpoint - 3):midpoint] or [0.0]) / max(len(view.funding_rates[max(0, midpoint - 3):midpoint] or [0.0]), 1)
            post_funding = sum(view.funding_rates[midpoint: midpoint + 3] or [0.0]) / max(len(view.funding_rates[midpoint: midpoint + 3] or [0.0]), 1)
            event.observed_impact = ObservedImpact(
                price_change_bps=((post_price - pre_price) / max(pre_price, 1e-9)) * 10_000,
                open_interest_change_pct=((post_oi - pre_oi) / max(abs(pre_oi), 1e-9)) * 100 if pre_oi else 0.0,
                funding_change_bps=(post_funding - pre_funding) * 10_000,
                measured_at=now,
            )
            self.store.upsert_event(event)

    def assess(self, symbol: str, venue: str, features: FeatureSet, state: MarketStateStore, external: ExternalContext, regime: str) -> ImpactAssessment:
        del venue, features, external, regime
        self.observe_market(symbol, state)
        assessment = ImpactAssessment()
        relevant = [event for event in self.events.values() if event.lifecycle != "expired" and self._symbol_matches(event, symbol)]
        if not relevant:
            return assessment
        confidence_multiplier = 1.0
        risk_multiplier = 1.0
        suppress = False
        delay_seconds = 0
        reasons: list[str] = []
        cooldown_until = None
        regime_modifier = None
        now = datetime.now(timezone.utc)
        for event in relevant:
            decay = self._impact_decay(event)
            influence = max(0.15, min(1.0, event.severity * decay * max(event.consensus_score, 0.8)))
            confidence_multiplier *= max(0.35, 1 - 0.25 * influence)
            risk_multiplier *= 1 + 0.35 * influence
            if event.category in {"incident", "macro", "whale"}:
                regime_modifier = "high_stress"
            if event.severity >= 0.85 and event.lifecycle in {"confirmed", "escalating", "peak"}:
                suppress = True
            elif event.severity >= 0.7:
                delay_seconds = max(delay_seconds, 300)
            cooldown_minutes = int(30 + event.severity * 180)
            if event.lifecycle in {"resolved", "decay"}:
                cooldown_minutes = max(15, cooldown_minutes // 2)
            event.cooldown_until = event.cooldown_until or (now + timedelta(minutes=cooldown_minutes))
            if event.cooldown_until and event.cooldown_until > now:
                cooldown_until = max(cooldown_until or event.cooldown_until, event.cooldown_until)
                if event.severity >= 0.8:
                    suppress = True
            reasons.append(f"{event.category}:{event.source_name}")
        assessment.confidence_multiplier = confidence_multiplier
        assessment.risk_multiplier = risk_multiplier
        assessment.regime_modifier = regime_modifier
        assessment.suppress = suppress
        assessment.delay_seconds = delay_seconds
        assessment.reasons = reasons
        assessment.cooldown_until = cooldown_until
        assessment.active_events = relevant
        for event in relevant:
            self.store.record_assessment(event.event_id, assessment)
        return assessment
