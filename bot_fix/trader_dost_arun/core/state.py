from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median

from trader_dost_arun.core.models import Direction, LiquidationEvent, MarketSnapshot, MarketStateView, StrategyPerformance, Trade, utc_now
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
class KeyedSeries:
    closes: deque = field(default_factory=lambda: deque(maxlen=4000))
    highs: deque = field(default_factory=lambda: deque(maxlen=4000))
    lows: deque = field(default_factory=lambda: deque(maxlen=4000))
    volumes: deque = field(default_factory=lambda: deque(maxlen=4000))
    open_interests: deque = field(default_factory=lambda: deque(maxlen=4000))
    funding_rates: deque = field(default_factory=lambda: deque(maxlen=4000))
    premiums: deque = field(default_factory=lambda: deque(maxlen=4000))
    # Cached z-score input series (finite-only *copy* of the series above, kept
    # in lockstep with each append so feature computation never rescans the
    # full deque per call). Bounded to maxlen.
    spread_series: deque = field(default_factory=lambda: deque(maxlen=4000))
    bid_depths: deque = field(default_factory=lambda: deque(maxlen=4000))
    ask_depths: deque = field(default_factory=lambda: deque(maxlen=4000))
    mark_prices: deque = field(default_factory=lambda: deque(maxlen=4000))
    index_prices: deque = field(default_factory=lambda: deque(maxlen=4000))
    # --- Incremental statistics (per-key) -------------------------------------
    # trade_delta: signed cumulative volume over last 200 trades
    trade_delta200: float = 0.0
    _trade_delta200_vals: deque = field(default_factory=lambda: deque(maxlen=4000))
    # cumulative volume delta over the entire trades window (cvd)
    cvd_total: float = 0.0
    vwap_price_volume_120: float = 0.0
    vwap_volume_120: float = 0.0
    vwap_price_volume_total: float = 0.0
    vwap_volume_total: float = 0.0
    _vwap_window: deque = field(default_factory=lambda: deque(maxlen=120))
    ofi_series: deque = field(default_factory=lambda: deque(maxlen=4000))
    option_atm_iv_series: deque = field(default_factory=lambda: deque(maxlen=4000))
    option_put_call_skew_series: deque = field(default_factory=lambda: deque(maxlen=4000))

    def push_snapshot(self, snapshot: MarketSnapshot, finite) -> None:
        mid = snapshot.mid_price
        if finite(mid) and float(mid) > 0:
            self.closes.append(float(mid))
        bid_depth = sum(level.size for level in snapshot.bid_levels[:10] if finite(level.size))
        ask_depth = sum(level.size for level in snapshot.ask_levels[:10] if finite(level.size))
        self.bid_depths.append(bid_depth)
        self.ask_depths.append(ask_depth)
        if finite(snapshot.spread):
            self.spread_series.append(float(snapshot.spread))
        highs = [lvl.price for lvl in snapshot.ask_levels[:3] if finite(lvl.price)]
        self.highs.append(max(highs) if highs else float(mid or 0.0))
        lows = [lvl.price for lvl in snapshot.bid_levels[:3] if finite(lvl.price)]
        self.lows.append(min(lows) if lows else float(mid or 0.0))
        if finite(snapshot.open_interest):
            self.open_interests.append(float(snapshot.open_interest))
        if finite(snapshot.funding_rate):
            self.funding_rates.append(float(snapshot.funding_rate))
        if finite(snapshot.premium):
            self.premiums.append(float(snapshot.premium))
        if finite(snapshot.mark_price):
            self.mark_prices.append(float(snapshot.mark_price))
        if finite(snapshot.index_price):
            self.index_prices.append(float(snapshot.index_price))
        denom = bid_depth + ask_depth
        if denom:
            self.ofi_series.append((bid_depth - ask_depth) / denom)
        if finite(snapshot.option_atm_iv):
            self.option_atm_iv_series.append(float(snapshot.option_atm_iv))
        if finite(snapshot.option_put_call_skew):
            self.option_put_call_skew_series.append(float(snapshot.option_put_call_skew))

    def push_trade(self, trade: Trade, finite_size: float) -> None:
        sign = 1.0 if trade.side == Direction.LONG else -1.0
        self.volumes.append(finite_size)
        # rolling signed trade_delta over last 200 trades
        if len(self._trade_delta200_vals) >= 200:
            oldest = self._trade_delta200_vals.popleft()
            self.trade_delta200 -= oldest
        self._trade_delta200_vals.append(sign * finite_size)
        self.trade_delta200 += sign * finite_size
        # cumulative over the bounded deque (cvd == full history vwap denominator accumulator)
        self.cvd_total += sign * finite_size
        price = float(trade.price) if trade.price and trade.price > 0 else 0.0
        vol = float(trade.size) if trade.size and trade.size > 0 else 0.0
        if price > 0 and vol > 0:
            if len(self._vwap_window) >= 120:
                oldp, oldv = self._vwap_window.popleft()
                self.vwap_price_volume_120 -= oldp * oldv
                self.vwap_volume_120 -= oldv
            self._vwap_window.append((price, vol))
            self.vwap_price_volume_120 += price * vol
            self.vwap_volume_120 += vol
            # session window (full deque history)
            self.vwap_price_volume_total += price * vol
            self.vwap_volume_total += vol


@dataclass(slots=True)
class MarketStateStore:
    maxlen: int = 2000
    snapshots: dict[str, deque[MarketSnapshot]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2000)))
    trades: dict[str, deque[Trade]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=4000)))
    liquidations: dict[str, deque[LiquidationEvent]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2000)))
    performances: dict[str, StrategyPerformance] = field(default_factory=lambda: defaultdict(StrategyPerformance))
    suppression_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # Per (venue:symbol) aggregated rolling series. Appending here is O(1);
    # features then read from these windowed deques instead of rescanning the
    # full snapshot list every evaluation (the O(history) rebuild that made
    # event-loop lag climb with history size).
    _series: dict[str, KeyedSeries] = field(default_factory=dict)

    def _key(self, venue: str, symbol: str) -> str:
        return f"{venue}:{symbol}"

    def _split_key(self, key: str) -> tuple[str, str]:
        return key.split(":", 1)

    def _identity(self, venue: str, symbol: str) -> InstrumentIdentity:
        return normalize_instrument(venue, symbol)

    def _finite(self, value: float | None) -> bool:
        return value is not None and math.isfinite(float(value))

    def _series_for(self, key: str) -> KeyedSeries:
        series = self._series.get(key)
        if series is None:
            series = KeyedSeries()
            self._series[key] = series
        return series

    def add_snapshot(self, snapshot: MarketSnapshot) -> None:
        key = self._key(snapshot.venue, snapshot.symbol)
        self.snapshots[key].append(snapshot)
        self._series_for(key).push_snapshot(snapshot, self._finite)

    def add_trade(self, trade: Trade) -> None:
        key = self._key(trade.venue, trade.symbol)
        self.trades[key].append(trade)
        if self._finite(trade.size):
            self._series_for(key).push_trade(trade, abs(float(trade.size)))

    def add_liquidation(self, event: LiquidationEvent) -> None:
        self.liquidations[self._key(event.venue, event.symbol)].append(event)

    def series(self, venue: str, symbol: str) -> "KeyedSeries | None":
        return self._series.get(self._key(venue, symbol))

    def view(self, venue: str, symbol: str) -> MarketStateView:
        key = self._key(venue, symbol)
        snaps = list(self.snapshots[key])
        trades = list(self.trades[key])
        liquidations = list(self.liquidations[key])
        # closes/highs/lows/depths/etc. are read from pre-aggregated per-key
        # deques (O(len) bounds the cost to the rolling window, not the full
        # maxlen history) instead of rescanning every snapshot on every call.
        series = self._series_for(key)
        closes = list(series.closes)
        highs = list(series.highs)
        lows = list(series.lows)
        volumes = [abs(float(t.size)) for t in trades if self._finite(t.size)]  # trades window is already bounded
        open_interests = list(series.open_interests)
        funding_rates = list(series.funding_rates)
        premiums = list(series.premiums)
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
            trade_delta200=series.trade_delta200 if series.trade_delta200 else 0.0,
            cvd_total=series.cvd_total,
            vwap_price_volume_120=series.vwap_price_volume_120,
            vwap_volume_120=series.vwap_volume_120,
            vwap_price_volume_total=series.vwap_price_volume_total,
            vwap_volume_total=series.vwap_volume_total,
            ofi_series=list(series.ofi_series),
            option_atm_iv_series=list(series.option_atm_iv_series),
            option_put_call_skew_series=list(series.option_put_call_skew_series),
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

    def rebuild_performance_from_history(self, realized_r_by_strategy: dict[str, list[float]]) -> None:
        """Replay real closed-trade history into self.performances.

        Call once at startup with PositionStore.get_closed_realized_r_by_strategy()
        so live win-rate/payoff-ratio (used for Kelly sizing and meta-label
        features) reflect this strategy's actual track record immediately,
        instead of resetting to the StrategyPerformance neutral prior
        (win_rate=0.5, payoff_ratio=1.0) on every restart and only becoming
        meaningful again after several fresh trades.
        """
        for strategy_name, realized_r_values in realized_r_by_strategy.items():
            for realized_r in realized_r_values:
                self.update_performance(strategy_name, realized_r)

    def spread_percentile(self, venue: str, symbol: str, current: float) -> float:
        series = self._series.get(self._key(venue, symbol))
        spreads = list(series.spread_series) if series else []
        if not spreads:
            return 0.5
        sorted_spreads = sorted(spreads)
        rank = sum(1 for value in sorted_spreads if value <= current)
        return rank / len(sorted_spreads)

    def same_side_depth_percentile(self, venue: str, symbol: str, current_depth: float) -> float:
        series = self._series.get(self._key(venue, symbol))
        if not series:
            return 0.5
        depths = list(series.bid_depths) + list(series.ask_depths)
        if not depths:
            return 0.5
        sorted_depths = sorted(depths)
        rank = sum(1 for value in sorted_depths if value <= current_depth)
        return rank / len(sorted_depths)

    def median_price(self, venue: str, symbol: str, window: int = 60) -> float:
        closes = self.view(venue, symbol).closes[-window:]
        return median(closes) if closes else 0.0
