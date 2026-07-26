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

    def freshness(self, venue: str, symbol: str, max_age_seconds: float, min_sources: int) -> FreshnessStatus:
        now = utc_now()
        identity = self._identity(venue, symbol)
        fresh_sources: list[str] = []
        stale_sources: dict[str, float] = {}
        own_age_seconds: float | None = None
        freshest_age_seconds: float | None = None
        for key, snapshots in self.snapshots.items():
            if not snapshots:
                continue
            peer_venue, peer_symbol = self._split_key(key)
            peer_identity = self._identity(peer_venue, peer_symbol)
            if peer_identity.canonical_symbol != identity.canonical_symbol:
                continue
            latest = snapshots[-1]
            event_age = max((now - latest.event_time).total_seconds(), 0.0)
            arrival_age = max((now - latest.arrival_time).total_seconds(), 0.0)
            age = max(event_age, arrival_age)
            freshest_age_seconds = age if freshest_age_seconds is None else min(freshest_age_seconds, age)
            if peer_venue == venue:
                own_age_seconds = age
            if age <= max_age_seconds:
                fresh_sources.append(peer_venue)
            else:
                stale_sources[peer_venue] = age
        return FreshnessStatus(
            canonical_symbol=identity.canonical_symbol,
            own_age_seconds=own_age_seconds,
            freshest_age_seconds=freshest_age_seconds,
            fresh_sources=tuple(sorted(fresh_sources)),
            stale_sources=stale_sources,
            total_sources=len(fresh_sources) + len(stale_sources),
            quorum_met=len(fresh_sources) >= max(1, min_sources),
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
