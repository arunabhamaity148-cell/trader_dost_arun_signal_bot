from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median

from trader_dost_arun.core.models import LiquidationEvent, MarketSnapshot, MarketStateView, StrategyPerformance, Trade


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
        closes = [s.mid_price for s in snaps if s.mid_price is not None]
        highs = [max([lvl.price for lvl in s.ask_levels[:3]], default=s.mid_price or 0.0) for s in snaps]
        lows = [min([lvl.price for lvl in s.bid_levels[:3]], default=s.mid_price or 0.0) for s in snaps]
        volumes = [abs(t.size) for t in trades]
        open_interests = [s.open_interest for s in snaps if s.open_interest is not None]
        funding_rates = [s.funding_rate for s in snaps if s.funding_rate is not None]
        premiums = [s.premium for s in snaps if s.premium is not None]
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

    def peer_views(self, symbol: str) -> dict[str, MarketStateView]:
        result: dict[str, MarketStateView] = {}
        for key in self.snapshots:
            venue, sym = key.split(":", 1)
            if sym == symbol:
                result[venue] = self.view(venue, sym)
        return result

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
        spreads = [s.spread for s in self.snapshots[self._key(venue, symbol)] if s.spread is not None]
        if not spreads:
            return 0.5
        sorted_spreads = sorted(spreads)
        rank = sum(1 for value in sorted_spreads if value <= current)
        return rank / len(sorted_spreads)

    def same_side_depth_percentile(self, venue: str, symbol: str, current_depth: float) -> float:
        depths = []
        for snap in self.snapshots[self._key(venue, symbol)]:
            depths.append(sum(level.size for level in snap.bid_levels[:10]))
            depths.append(sum(level.size for level in snap.ask_levels[:10]))
        if not depths:
            return 0.5
        sorted_depths = sorted(depths)
        rank = sum(1 for value in sorted_depths if value <= current_depth)
        return rank / len(sorted_depths)

    def median_price(self, venue: str, symbol: str, window: int = 60) -> float:
        closes = self.view(venue, symbol).closes[-window:]
        return median(closes) if closes else 0.0
