import json
import sqlite3
from pathlib import Path

from trader_dost_arun.backtest.engine import BacktestEngine
from trader_dost_arun.backtest.runner import build_html


def seed_db(path: Path) -> BacktestEngine:
    engine = BacktestEngine(db_path=path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO historical_signals(ts,symbol,strategy_name,direction,entry,stop,target,price_path_json,spread,same_side_depth,order_size,funding_rate,leverage,regime_at_entry,regime_at_exit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "2026-01-01T00:00:00",
                    "BTCUSDT",
                    "alpha",
                    "long",
                    100.0,
                    98.0,
                    104.0,
                    json.dumps([100.5, 101.0, 104.0]),
                    1.0,
                    1000.0,
                    1.0,
                    0.0001,
                    2.0,
                    "trending",
                    "trending",
                )
            ],
        )
    return engine


def test_backtest_html_contains_plotly_graph_div(tmp_path: Path):
    engine = seed_db(tmp_path / "hist.sqlite3")
    results = engine.run("BTCUSDT", days=5000, strategies=["all"])
    html = build_html(results)
    assert "plotly-graph-div" in html
    assert "Performance Metrics" in html
