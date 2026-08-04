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


def test_get_closed_realized_r_by_strategy_groups_and_excludes_open(tmp_path: Path):
    store = PositionStore(tmp_path / "positions.sqlite3")
    store.save_position(make_position())
    store.close_position("BTCUSDT", "binance", 104.0, 2.0, "target")
    # A second, still-open position for the same strategy must not appear -
    # only closed trades with a realized_r should feed performance rebuild.
    store.save_position(make_position())
    grouped = store.get_closed_realized_r_by_strategy()
    assert grouped == {"alpha": [2.0]}


def test_close_position_by_id_only_affects_that_row_not_other_open_positions_same_symbol(tmp_path: Path):
    """Two different strategies both open on the same symbol+venue must be
    closeable independently - closing one must not corrupt the other's
    still-open row, and must not overwrite it with the wrong exit data."""
    store = PositionStore(tmp_path / "positions.sqlite3")
    pos_a = make_position()  # strategy "alpha", BTCUSDT/binance
    pos_b = make_position()
    pos_b.signal.strategy_name = "beta"
    id_a = store.save_position(pos_a)
    id_b = store.save_position(pos_b)
    assert id_a != id_b

    store.close_position_by_id(id_a, exit_price=104.0, realized_r=2.0, exit_reason="target")

    history = {row["strategy_name"]: row for row in store.get_history(limit=10)}
    assert history["alpha"]["closed_at"] is not None
    assert history["alpha"]["realized_r"] == 2.0
    # beta's position must remain open and untouched
    assert history["beta"]["closed_at"] is None
    assert history["beta"]["realized_r"] is None
    open_positions = store.load_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].signal.strategy_name == "beta"
