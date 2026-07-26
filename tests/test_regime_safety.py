import asyncio

import numpy as np
import pytest

from trader_dost_arun.adaptive.regime import FALLBACK_LABELS, HMMRegimeDetector, _FitResult


@pytest.mark.asyncio
async def test_regime_detector_rejects_nan_and_inf_samples():
    detector = HMMRegimeDetector(min_samples=3, fit_interval_seconds=3600)
    await detector.observe(0.1, 1.0, 0.01)
    await detector.observe(float("nan"), 1.0, 0.01)
    await detector.observe(0.2, float("inf"), 0.01)
    assert len(detector.samples) == 1
    assert detector.current().label == "warmup"


@pytest.mark.asyncio
async def test_regime_detector_handles_fit_exceptions_without_leaking_task(monkeypatch):
    detector = HMMRegimeDetector(min_samples=3, fit_interval_seconds=0, transition_confirmation_ticks=1)

    def boom(matrix):
        raise ValueError("bad matrix")

    monkeypatch.setattr(detector, "_fit_model", boom)
    await detector.observe(0.1, 1.0, 0.01)
    await detector.observe(0.2, 1.1, 0.01)
    await detector.observe(0.3, 1.2, 0.01)
    await asyncio.sleep(0.05)
    await detector.observe(0.4, 1.3, 0.01)
    assert detector.model == "fallback"
    assert detector.state_labels == FALLBACK_LABELS


@pytest.mark.asyncio
async def test_regime_detector_successful_fit_updates_model(monkeypatch):
    detector = HMMRegimeDetector(min_samples=3, fit_interval_seconds=0, transition_confirmation_ticks=1)

    class FakeModel:
        def predict_proba(self, matrix):
            return np.array([[0.1, 0.8, 0.1]], dtype=float)

    monkeypatch.setattr(detector, "_fit_model", lambda matrix: _FitResult(model=FakeModel(), state_labels={1: "trending"}))
    await detector.observe(0.1, 1.0, 0.01)
    await detector.observe(0.2, 1.1, 0.01)
    await detector.observe(0.3, 1.2, 0.01)
    await asyncio.sleep(0.05)
    await detector.observe(0.4, 1.3, 0.01)
    assert detector.current().label == "trending"
    assert detector.current().state_id == 1


@pytest.mark.asyncio
async def test_regime_detector_keeps_warmup_on_insufficient_valid_history():
    detector = HMMRegimeDetector(min_samples=5, fit_interval_seconds=0)
    for vol in [0.1, 0.2, 0.3, 0.4]:
        await detector.observe(vol, 1.0, 0.01)
    assert detector.current().label == "warmup"
