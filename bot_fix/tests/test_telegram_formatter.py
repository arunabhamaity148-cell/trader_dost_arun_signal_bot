from pathlib import Path

from trader_dost_arun.core.models import Direction, Signal
from trader_dost_arun.ops.alerts import TelegramAlerter


def sample_signal() -> Signal:
    return Signal(
        strategy_name="liquidation_cascade_continuation",
        symbol="BTCUSDT",
        venue="binance",
        direction=Direction.LONG,
        entry=67234.55,
        stop=66990.12,
        targets=[67698.45, 68162.35, 68626.25],
        confidence=78.4,
        advisory_size_fraction=0.024,
        regime="trending",
        confirmations=["Liquidation cascade detected (z-score 3.2)", "Range breakout confirmed", "Delta OI aligned with direction", "Adverse depth not replenishing", "Microprice leading mid-price"],
        vetoes_checked={f"check_{i}": True for i in range(21)},
        metadata={"meta_probability": 0.672, "bayesian_confidence": 82.1, "calibrated_confidence": 74.8, "live_win_rate": 71, "live_samples": 24, "regime_weight": 1.22, "confluence_score": 8, "valid_window": "2-5 min", "cooldown_minutes": 8, "next_funding_minutes": 23, "news_guard": "No Active Threats", "whale_flow": "Net +$2.3M (bullish)", "structural": {"timeframe": "4h"}},
    )


def test_formatter_includes_header(tmp_path: Path):
    text = TelegramAlerter("", "", tmp_path / "counter.sqlite3").render_signal(sample_signal())
    assert "ELITE SIGNAL" in text


def test_formatter_shows_trade_plan(tmp_path: Path):
    text = TelegramAlerter("", "", tmp_path / "counter.sqlite3").render_signal(sample_signal())
    assert "TRADE PLAN" in text
    assert "Risk:Reward" in text


def test_formatter_shows_confidence_bar(tmp_path: Path):
    text = TelegramAlerter("", "", tmp_path / "counter.sqlite3").render_signal(sample_signal())
    assert "████" in text


def test_formatter_computes_leverage_and_margin(tmp_path: Path):
    text = TelegramAlerter("", "", tmp_path / "counter.sqlite3").render_signal(sample_signal())
    assert "Leverage:" in text
    assert "Margin (1k):" in text


def test_counter_persists_between_calls(tmp_path: Path):
    alerter = TelegramAlerter("", "", tmp_path / "counter.sqlite3")
    first = alerter.render_signal(sample_signal())
    second = alerter.render_signal(sample_signal())
    assert "#1" in first
    assert "#2" in second
