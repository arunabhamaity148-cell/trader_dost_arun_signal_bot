import json
import sqlite3
from pathlib import Path

from trader_dost_arun.backtest.engine import BacktestEngine
from trader_dost_arun.backtest.metrics import calmar, expectancy, max_drawdown, profit_factor, regime_breakdown, sharpe, sortino


def seed_db(path: Path):
    engine = BacktestEngine(db_path=path)
    with sqlite3.connect(path) as conn:
        rows = [
            ("2026-01-01T00:00:00", "BTCUSDT", "alpha", "long", 100.0, 98.0, 104.0, json.dumps([100.5, 101.0, 104.0]), 1.0, 1000.0, 1.0, 0.0001, 2.0, "trending", "trending"),
            ("2026-01-02T00:00:00", "BTCUSDT", "alpha", "long", 100.0, 98.0, 104.0, json.dumps([99.5, 98.5, 98.0]), 1.0, 1000.0, 1.0, 0.0001, 2.0, "trending", "mean_reverting"),
            ("2026-01-03T00:00:00", "BTCUSDT", "beta", "short", 100.0, 102.0, 96.0, json.dumps([99.0, 98.0, 96.0]), 1.0, 1000.0, 1.0, 0.0001, 3.0, "high_stress", "high_stress"),
        ]
        conn.executemany(
            "INSERT INTO historical_signals(ts,symbol,strategy_name,direction,entry,stop,target,price_path_json,spread,same_side_depth,order_size,funding_rate,leverage,regime_at_entry,regime_at_exit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return engine


def test_slippage_modeling_changes_fill(tmp_path: Path):
    engine = seed_db(tmp_path / "hist.sqlite3")
    results = engine.run("BTCUSDT", days=5000, strategies=["alpha"])
    assert results["alpha"].rows[0]["fill_price"] > 100.0


def test_liquidation_rule(tmp_path: Path):
    engine = BacktestEngine(db_path=tmp_path / "hist.sqlite3")
    realized, reason = engine._simulate_trade(100, 100.5, 98, 104, [99, 98.3, 98.2], 3, 0.0, "long")
    assert reason == "liquidation"
    assert realized == -3.0


def test_funding_cost_is_subtracted(tmp_path: Path):
    engine = BacktestEngine(db_path=tmp_path / "hist.sqlite3")
    realized, reason = engine._simulate_trade(100, 100, 98, 104, [101, 102, 104], 1, 0.1, "long")
    assert reason == "target"
    assert realized < 2.0


def test_metric_calculations():
    returns = [0.2, -0.1, 0.3, 0.05]
    equity = [1.0, 1.2, 1.08, 1.404, 1.4742]
    assert sharpe(returns) != 0
    assert sortino(returns) != 0
    assert max_drawdown(equity) > 0
    assert calmar(equity[-1] - 1.0, equity) > 0
    assert profit_factor(returns) > 1
    assert expectancy(returns) > 0


def test_regime_tagging_breakdown():
    breakdown = regime_breakdown([
        {"strategy_name": "alpha", "regime_at_exit": "trending", "realized_r": 1.0},
        {"strategy_name": "alpha", "regime_at_exit": "trending", "realized_r": -0.5},
    ])
    assert "alpha::trending" in breakdown
    assert breakdown["alpha::trending"]["count"] == 2.0


def test_backtest_engine_returns_metrics(tmp_path: Path):
    engine = seed_db(tmp_path / "hist.sqlite3")
    results = engine.run("BTCUSDT", days=5000, strategies=["all"])
    assert set(results) == {"alpha", "beta"}
    assert "sharpe" in results["alpha"].metrics()


def test_equity_curve_export(tmp_path: Path):
    engine = seed_db(tmp_path / "hist.sqlite3")
    results = engine.run("BTCUSDT", days=5000, strategies=["all"])
    csv_path = tmp_path / "curve.csv"
    engine.export_equity_curve(results, csv_path)
    assert csv_path.exists()
    assert "strategy_name" in csv_path.read_text(encoding="utf-8")


def test_runner_report_generation(tmp_path: Path):
    engine = seed_db(tmp_path / "hist.sqlite3")
    results = engine.run("BTCUSDT", days=5000, strategies=["all"])
    html = __import__("trader_dost_arun.backtest.runner", fromlist=["build_html"]).build_html(results)
    assert "Backtest" in html
    assert "alpha" in html
