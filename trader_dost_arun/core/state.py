from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median

from trader_dost_arun.core.models import LiquidationEvent, MarketSnapshot, MarketStateView, StrategyPerformance, Trade, utc_now
from trader_dost_arun.core.symbols import InstrumentIdentity, normalize_instrument


@dataclass(slots=True)
class FreshnessStatus:
    canonical_symbol: str
    own_age_seconds: float | None
    freshest_age_seconds: float | None
    fresh_sources: tuple[str, ...]
    stale_sources: dict[str, float]
    total_sources: int
    quorum_met: bool
    own_enrichment_age_seconds: float | None = None
    latest_enrichment_age_seconds: float | None = None
    last_valid_market_update: str | None = None
    freshness_rejection_reason: str | None = None


@dataclass(slots=True)
class MarketStateStore:
    maxlen: int = 2000
    snapshots: dict[str, deque[MarketSnapshot]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2000)))
    trades: dict[str, deque[Trade]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=4000)))
    liquidations: dict[str, deque[LiquidationEvent]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2000)))
    performances: dict[str, StrategyPerformance] = field(default_factory=lambda: defaultdict(StrategyPerformance))
    suppression_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def _key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def _split_key(self, key: str) -> tuple[str, str]:
        return key.split(":", 1)

    def _identity(self, venue: str, symbol: str) -> InstrumentIdentity:
        return normalize_instrument(venue, symbol)

    def _finite(self, value: float | None) -> bool:
        return value is not None and math.isfinite(float(value))

    def add_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.snapshots[self._key(snapshot.venue, snapshot.symbol)].append(snapshot)

    def add_trade(self, trade: Trade) -> None:
        self.trades[self._key(trade.venue, trade.symbol)].append(trade)

    def add_liquidation(self, event: LiquidationEvent) -> None:
        self.liquidations[self._key(event.venue, event.symbol)].append(event)

    def view(self, venue: str, symbol: str) -> MarketStateView:
        key = self._key(venue, symbol)
        snaps = list(self.snapshots[key])
        trades = list(self.trades[key])
        liquidations = list(self.liquidations[key])
        closes = [float(s.mid_price) for s in snaps if self._finite(s.mid_price) and float(s.mid_price) > 0]
        highs = [max([lvl.price for lvl in s.ask_levels[:3] if self._finite(lvl.price)], default=float(s.mid_price or 0.0)) for s in snaps]
        lows = [min([lvl.price for lvl in s.bid_levels[:3] if self._finite(lvl.price)], default=float(s.mid_price or 0.0)) for s in snaps]
        volumes = [abs(float(t.size)) for t in trades if self._finite(t.size)]
        open_interests = [float(s.open_interest) for s in snaps if self._finite(s.open_interest)]
        funding_rates = [float(s.funding_rate) for s in snaps if self._finite(s.funding_rate)]
        premiums = [float(s.premium) for s in snaps if self._finite(s.premium)]
        return MarketStateView(
            symbol=symbol,
            snapshots=snaps,
            trades=trades,
            liquidations=liquidations,
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            open_interests=open_interests,
            funding_rates=funding_rates,
            premiums=premiums,
        )

    def peer_views(self, symbol: str, venue: str | None = None) -> dict[str, MarketStateView]:
        if venue is None:
            for key in self.snapshots:
                peer_venue, peer_symbol = self._split_key(key)
                if peer_symbol == symbol:
                    venue = peer_venue
                    break
        identity = self._identity(venue or "", symbol)
        result: dict[str, MarketStateView] = {}
        for key in self.snapshots:
            peer_venue, peer_symbol = self._split_key(key)
            peer_identity = self._identity(peer_venue, peer_symbol)
            if peer_identity.canonical_symbol == identity.canonical_symbol:
                result[peer_venue] = self.view(peer_venue, peer_symbol)
        return result

    def _snapshot_core_age(self, snapshot: MarketSnapshot) -> float | None:
        core_event_time = snapshot.core_event_time or snapshot.event_time
        core_arrival_time = snapshot.core_arrival_time or snapshot.arrival_time
        if core_event_time is None or core_arrival_time is None:
            return None
        now = utc_now()
        event_age = max((now - core_event_time).total_seconds(), 0.0)
        arrival_age = max((now - core_arrival_time).total_seconds(), 0.0)
        return max(event_age, arrival_age)

    def _snapshot_enrichment_age(self, snapshot: MarketSnapshot) -> float | None:
        if snapshot.enrichment_event_time is None:
            return None
        now = utc_now()
        arrival_ref = snapshot.enrichment_arrival_time or snapshot.arrival_time
        event_age = max((now - snapshot.enrichment_event_time).total_seconds(), 0.0)
        arrival_age = max((now - arrival_ref).total_seconds(), 0.0)
        return max(event_age, arrival_age)

    def freshness(self, venue: str, symbol: str, max_age_seconds: float, min_sources: int) -> FreshnessStatus:
        identity = self._identity(venue, symbol)
        fresh_sources: list[str] = []
        stale_sources: dict[str, float] = {}
        own_age_seconds: float | None = None
        freshest_age_seconds: float | None = None
        own_enrichment_age_seconds: float | None = None
        latest_enrichment_age_seconds: float | None = None
        last_valid_market_update = None
        for key, snapshots in self.snapshots.items():
            if not snapshots:
                continue
            peer_venue, peer_symbol = self._split_key(key)
            peer_identity = self._identity(peer_venue, peer_symbol)
            if peer_identity.canonical_symbol != identity.canonical_symbol:
                continue
            latest = snapshots[-1]
            core_age = self._snapshot_core_age(latest)
            enrichment_age = self._snapshot_enrichment_age(latest)
            if enrichment_age is not None:
                latest_enrichment_age_seconds = (
                    enrichment_age
                    if latest_enrichment_age_seconds is None
                    else min(latest_enrichment_age_seconds, enrichment_age)
                )
            if core_age is None:
                stale_sources[peer_venue] = float("inf")
                continue
            freshest_age_seconds = core_age if freshest_age_seconds is None else min(freshest_age_seconds, core_age)
            if peer_venue == venue:
                own_age_seconds = core_age
                own_enrichment_age_seconds = enrichment_age
                core_ts = latest.core_event_time or latest.event_time
                last_valid_market_update = core_ts.isoformat() if core_ts is not None else None
            if core_age <= max_age_seconds:
                fresh_sources.append(peer_venue)
            else:
                stale_sources[peer_venue] = core_age
        quorum_met = len(fresh_sources) >= max(1, min_sources)
        rejection_reason = None
        if own_age_seconds is None:
            rejection_reason = "missing_core_market_data"
        elif own_age_seconds > max_age_seconds:
            rejection_reason = "stale_core_market_data"
        elif not quorum_met:
            rejection_reason = "freshness_quorum_not_met"
        return FreshnessStatus(
            canonical_symbol=identity.canonical_symbol,
            own_age_seconds=own_age_seconds,
            freshest_age_seconds=freshest_age_seconds,
            fresh_sources=tuple(sorted(fresh_sources)),
            stale_sources=stale_sources,
            total_sources=len(fresh_sources) + len(stale_sources),
            quorum_met=quorum_met,
            own_enrichment_age_seconds=own_enrichment_age_seconds,
            latest_enrichment_age_seconds=latest_enrichment_age_seconds,
            last_valid_market_update=last_valid_market_update,
            freshness_rejection_reason=rejection_reason,
        )

    def update_performance(self, strategy_name: str, realized_r: float) -> None:
        perf = self.performances[strategy_name]
        perf.total_r += realized_r
        if realized_r > 0:
            perf.wins += 1
            perf.total_wins_r += realized_r
        else:
            perf.losses += 1
            perf.total_losses_r += realized_r

    def spread_percentile(self, venue: str, symbol: str, current: float) -> float:
        spreads = [float(s.spread) for s in self.snapshots[self._key(venue, symbol)] if self._finite(s.spread)]
        if not spreads:
            return 0.5
        sorted_spreads = sorted(spreads)
        rank = sum(1 for value in sorted_spreads if value <= current)
        return rank / len(sorted_spreads)

    def same_side_depth_percentile(self, venue: str, symbol: str, current_depth: float) -> float:
        depths = []
        for snap in self.snapshots[self._key(venue, symbol)]:
            bid_depth = sum(level.size for level in snap.bid_levels[:10] if self._finite(level.size))
            ask_depth = sum(level.size for level in snap.ask_levels[:10] if self._finite(level.size))
            depths.extend([bid_depth, ask_depth])
        if not depths:
            return 0.5
        sorted_depths = sorted(depths)
        rank = sum(1 for value in sorted_depths if value <= current_depth)
        return rank / len(sorted_depths)

    def median_price(self, venue: str, symbol: str, window: int = 60) -> float:
        closes = self.view(venue, symbol).closes[-window:]
        return median(closes) if closes else 0.0
