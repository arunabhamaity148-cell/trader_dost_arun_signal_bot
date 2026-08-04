import random

from trader_dost_arun.data.base import compute_backoff_delay, should_reset_retry_state


def test_backoff_delay_stays_within_jitter_bounds():
    delay = compute_backoff_delay(3, base_delay=1.0, max_delay=30.0, jitter_ratio=0.2, rng=random.Random(7))
    assert 3.2 <= delay <= 4.8


def test_backoff_delay_respects_cap_after_jitter():
    delay = compute_backoff_delay(10, base_delay=1.0, max_delay=30.0, jitter_ratio=0.2, rng=random.Random(1))
    assert 24.0 <= delay <= 30.0


def test_retry_state_resets_only_after_stable_connection():
    assert should_reset_retry_state(25.0, had_messages=True, stable_window_seconds=20.0) is True
    assert should_reset_retry_state(19.9, had_messages=True, stable_window_seconds=20.0) is False
    assert should_reset_retry_state(25.0, had_messages=False, stable_window_seconds=20.0) is False
