from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import mean
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(slots=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(slots=True)
class Trade:
    venue: str
    symbol: str
    price: float
    size: float
    side: Direction
    event_time: datetime
    arrival_time: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class LiquidationEvent:
    venue: str
    symbol: str
    side: Direction
    price: float
    size: float
    event_time: datetime
    arrival_time: datetime = field(default_factory=utc_now)

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass(slots=True)
class MarketSnapshot:
    venue: str
    symbol: str
    event_time: datetime
    bid_levels: list[OrderBookLevel] = field(default_factory=list)
    ask_levels: list[OrderBookLevel] = field(default_factory=list)
    last_trade: Trade | None = None
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    premium: float | None = None
    spread: float | None = None
    option_atm_iv: float | None = None
    option_put_call_skew: float | None = None
    arrival_time: datetime = field(default_factory=utc_now)
    core_event_time: datetime | None = None
    core_arrival_time: datetime | None = None
    enrichment_event_time: datetime | None = None
    enrichment_arrival_time: datetime | None = None
    update_class: str = "core"

    @property
    def mid_price(self) -> float | None:
        if self.bid_levels and self.ask_levels:
            return (self.bid_levels[0].price + self.ask_levels[0].price) / 2
        return self.mark_price or self.index_price

    @property
    def microprice(self) -> float | None:
        if self.bid_levels and self.ask_levels:
            bid = self.bid_levels[0]
            ask = self.ask_levels[0]
            denom = bid.size + ask.size
            if denom > 0:
                return (ask.price * bid.size + bid.price * ask.size) / denom
        return self.mid_price


@dataclass(slots=True)
class FeatureSet:
    venue: str
    symbol: str
    timestamp: datetime
    values: dict[str, float | int | bool | str] = field(default_factory=dict)

    def get(self, name: str, default: float = 0.0) -> float:
        value = self.values.get(name, default)
        return float(value) if isinstance(value, (int, float, bool)) else default


@dataclass(slots=True)
class StructuralState:
    bos: bool = False
    choch: bool = False
    bullish_fvg_open: bool = False
    bearish_fvg_open: bool = False
    bullish_order_block_active: bool = False
    bearish_order_block_active: bool = False
    bullish_sweep: bool = False
    bearish_sweep: bool = False
    trend_alignment: Direction = Direction.FLAT
    oi_alignment: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def contradicts(self, direction: Direction) -> bool:
        if self.trend_alignment == Direction.FLAT:
            return False
        if not self.oi_alignment:
            return True
        return self.trend_alignment != direction


@dataclass(slots=True)
class Signal:
    strategy_name: str
    symbol: str
    venue: str
    direction: Direction
    entry: float
    stop: float
    targets: list[float]
    confidence: float
    advisory_size_fraction: float
    regime: str
    confirmations: list[str]
    vetoes_checked: dict[str, bool]
    suppressed_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def expected_reward(self) -> float:
        return abs((self.targets[0] if self.targets else self.entry) - self.entry)

    @property
    def stop_pct(self) -> float:
        return abs(self.entry - self.stop) / max(abs(self.entry), 1e-9)


@dataclass(slots=True)
class HypotheticalPosition:
    signal: Signal
    opened_at: datetime = field(default_factory=utc_now)
    closed_at: datetime | None = None
    exit_price: float | None = None
    realized_r_multiple: float | None = None
    outcome: int | None = None
    leverage: float = 1.0
    fill_price: float | None = None
    funding_cost: float = 0.0
    exit_reason: str | None = None


@dataclass(slots=True)
class VenueHealth:
    venue: str
    score: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    reconnect_count: int
    stale_seconds: float
    veto_failure_rate: float
    error_rate: float
    status: str = "healthy"
    sample_count: int = 0


@dataclass(slots=True)
class StrategyPerformance:
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    total_wins_r: float = 0.0
    total_losses_r: float = 0.0

    @property
    def sample_size(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.sample_size if self.sample_size else 0.5

    @property
    def payoff_ratio(self) -> float:
        if self.wins == 0 or self.losses == 0:
            return 1.0
        avg_win = self.total_wins_r / max(self.wins, 1)
        avg_loss = abs(self.total_losses_r) / max(self.losses, 1)
        return max(avg_win / max(avg_loss, 1e-6), 0.1)

    @property
    def profit_factor(self) -> float:
        return self.total_wins_r / max(abs(self.total_losses_r), 1e-9) if self.losses else max(self.total_wins_r, 1.0)


@dataclass(slots=True)
class RegimeRecord:
    label: str
    state_id: int
    probabilities: list[float]
    features: list[float]
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MarketStateView:
    symbol: str
    snapshots: list[MarketSnapshot]
    trades: list[Trade]
    liquidations: list[LiquidationEvent]
    closes: list[float]
    highs: list[float]
    lows: list[float]
    volumes: list[float]
    open_interests: list[float]
    funding_rates: list[float]
    premiums: list[float]

    @property
    def latest(self) -> MarketSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def rolling_mean(self, values: list[float], n: int) -> float:
        sample = values[-n:] if len(values) >= n else values
        return mean(sample) if sample else 0.0
