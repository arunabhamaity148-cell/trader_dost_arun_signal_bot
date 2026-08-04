from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trader_dost_arun.backtest.metrics import calmar, expectancy, max_drawdown, profit_factor, regime_breakdown, sharpe, sortino
from trader_dost_arun.execution.slippage import SlippageModel


@dataclass(slots=True)
class BacktestResult:
    strategy_name: str
    returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=lambda: [1.0])
    rows: list[dict[str, Any]] = field(default_factory=list)

    def metrics(self) -> dict[str, float | dict[str, dict[str, float]]]:
        total_return = self.equity_curve[-1] - 1.0
        wins = sum(1 for x in self.returns if x > 0)
        losses = sum(1 for x in self.returns if x < 0)
        avg_win = sum(x for x in self.returns if x > 0) / max(wins, 1)
        avg_loss = abs(sum(x for x in self.returns if x < 0)) / max(losses, 1) if losses else 1.0
        return {
            "total_return": total_return,
            "sharpe": sharpe(self.returns),
            "sortino": sortino(self.returns),
            "max_drawdown": max_drawdown(self.equity_curve),
            "win_rate": wins / max(len(self.returns), 1),
            "payoff_ratio": avg_win / max(avg_loss, 1e-9) if losses else 1.0,
            "profit_factor": profit_factor(self.returns),
            "expectancy": expectancy(self.returns),
            "calmar": calmar(total_return, self.equity_curve),
            "regimes": regime_breakdown(self.rows),
        }


class BacktestEngine:
    def __init__(self, db_path: str | Path = "./data/historical.sqlite3", mode: str = "event-driven", slippage_mode: str = "conservative") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.slippage = SlippageModel(mode=slippage_mode)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_signals (
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    target REAL NOT NULL,
                    price_path_json TEXT NOT NULL,
                    spread REAL DEFAULT 1.0,
                    same_side_depth REAL DEFAULT 1000.0,
                    order_size REAL DEFAULT 1.0,
                    funding_rate REAL DEFAULT 0.0,
                    leverage REAL DEFAULT 1.0,
                    regime_at_entry TEXT DEFAULT 'unknown',
                    regime_at_exit TEXT DEFAULT 'unknown',
                    fill_price REAL,
                    slippage_bps REAL,
                    funding_cost REAL,
                    exit_reason TEXT
                )
                """
            )

    def run(self, symbol: str, days: int = 90, strategies: list[str] | None = None) -> dict[str, BacktestResult]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        placeholders = "" if not strategies or strategies == ["all"] else " AND strategy_name IN (%s)" % ",".join("?" for _ in strategies)
        params: list[Any] = [symbol, cutoff]
        if strategies and strategies != ["all"]:
            params.extend(strategies)
        results: dict[str, BacktestResult] = {}
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ts, strategy_name, direction, entry, stop, target, price_path_json, spread, same_side_depth, order_size, funding_rate, leverage, regime_at_exit FROM historical_signals WHERE symbol = ? AND ts >= ?" + placeholders,
                params,
            )
            for ts, strategy_name, direction, entry, stop, target, price_path_json, spread, same_side_depth, order_size, funding_rate, leverage, regime_at_exit in cur.fetchall():
                result = results.setdefault(strategy_name, BacktestResult(strategy_name=strategy_name))
                path = [float(x) for x in __import__("json").loads(price_path_json)]
                fill_price, slip_bps = self.slippage.expected_fill_price(float(entry), __import__("trader_dost_arun.core.models", fromlist=["Direction"]).Direction(direction), float(spread), float(order_size), float(same_side_depth))
                funding_cost = abs(float(funding_rate)) * len(path)
                realized, exit_reason = self._simulate_trade(float(entry), fill_price, float(stop), float(target), path, float(leverage), funding_cost, direction)
                result.returns.append(realized)
                result.equity_curve.append(result.equity_curve[-1] * (1 + realized))
                result.rows.append({"ts": ts, "strategy_name": strategy_name, "realized_r": realized, "regime_at_exit": regime_at_exit, "exit_reason": exit_reason, "fill_price": fill_price, "slippage_bps": slip_bps, "funding_cost": funding_cost, "leverage": leverage})
        return results

    def _simulate_trade(self, entry: float, fill_price: float, stop: float, target: float, path: list[float], leverage: float, funding_cost: float, direction: str) -> tuple[float, str]:
        risk = abs(entry - stop) or 1e-9
        liquidation_level = entry - 0.8 * risk if direction == "long" else entry + 0.8 * risk
        for px in path:
            if direction == "long":
                if px <= liquidation_level:
                    return -1.0 * leverage, "liquidation"
                if px <= stop:
                    return ((stop - fill_price) / risk) - funding_cost, "stop"
                if px >= target:
                    return ((target - fill_price) / risk) - funding_cost, "target"
            else:
                if px >= liquidation_level:
                    return -1.0 * leverage, "liquidation"
                if px >= stop:
                    return ((fill_price - stop) / risk) - funding_cost, "stop"
                if px <= target:
                    return ((fill_price - target) / risk) - funding_cost, "target"
        final = path[-1] if path else fill_price
        realized = ((final - fill_price) / risk) if direction == "long" else ((fill_price - final) / risk)
        return realized - funding_cost, "time"

    def export_equity_curve(self, results: dict[str, BacktestResult], output_csv: str | Path) -> None:
        output = Path(output_csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["strategy_name", "step", "equity"])
            for strategy, result in results.items():
                for step, equity in enumerate(result.equity_curve):
                    writer.writerow([strategy, step, equity])
