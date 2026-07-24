from datetime import datetime, timezone
from pathlib import Path

from trader_dost_arun.core.models import Direction, HypotheticalPosition, Signal
from trader_dost_arun.core.persistence import PositionStore


def make_position() -> HypotheticalPosition:
    signal = Signal(
        strategy_name="alpha",
        symbol="BTCUSDT",
        venue="binance",
        direction=Direction.LONG,
        entry=100.0,
        stop=98.0,
        targets=[104.0],
        confidence=75.0,
        advisory_size_fraction=0.01,
        regime="trending",
        confirmations=[],
        vetoes_checked={},
        created_at=datetime.now(timezone.utc),
    )
    return HypotheticalPosition(signal=signal)


def test_save_and_load_open_positions(tmp_path: Path):
    store = PositionStore(tmp_path / "positions.sqlite3")
    store.save_position(make_position())
    assert len(store.load_open_positions()) == 1


def test_close_position_updates_history(tmp_path: Path):
    store = PositionStore(tmp_path / "positions.sqlite3")
    store.save_position(make_position())
    store.close_position("BTCUSDT", "binance", 104.0, 2.0, "target")
    history = store.get_history()
    assert history[0]["exit_reason"] == "target"


def test_history_returns_closed_positions(tmp_path: Path):
    store = PositionStore(tmp_path / "positions.sqlite3")
    store.save_position(make_position())
    assert store.get_history(limit=10)
