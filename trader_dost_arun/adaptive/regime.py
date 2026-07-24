from __future__ import annotations

import asyncio
import math
import time
from collections import Counter, deque
from dataclasses import dataclass

import numpy as np

try:
    from hmmlearn.hmm import GaussianHMM
except Exception:  # noqa: BLE001
    GaussianHMM = None

from trader_dost_arun.core.models import RegimeRecord, utc_now


@dataclass(slots=True)
class _FitResult:
    model: object | None
    state_labels: dict[int, str]


class HMMRegimeDetector:
    def __init__(
        self,
        n_components: int = 3,
        min_samples: int = 500,
        fit_interval_seconds: int = 300,
        transition_confirmation_ticks: int = 3,
    ) -> None:
        self.n_components = n_components
        self.min_samples = min_samples
        self.fit_interval_seconds = fit_interval_seconds
        self.transition_confirmation_ticks = transition_confirmation_ticks
        self.samples: deque[list[float]] = deque(maxlen=5000)
        self.model: object | None = None
        self.state_labels: dict[int, str] = {}
        self.last_fit_started_at = 0.0
        self._fit_task: asyncio.Task | None = None
        self._current_label = "warmup"
        self._current_state = -1
        self._current_probabilities = [1.0]
        self._prediction_history: deque[str] = deque(maxlen=10)

    async def observe(self, vol: float, trend_strength: float, funding_regime: float) -> None:
        self.samples.append([float(vol), float(trend_strength), float(funding_regime)])
        if len(self.samples) < self.min_samples:
            self._set_warmup()
            return
        if self._fit_task and self._fit_task.done():
            result = self._fit_task.result()
            self.model = result.model
            self.state_labels = result.state_labels
            self._fit_task = None
        now = time.monotonic()
        if self._needs_refit(now):
            self.last_fit_started_at = now
            matrix = np.array(self.samples, dtype=float)
            self._fit_task = asyncio.create_task(asyncio.to_thread(self._fit_model, matrix))
        if self.model is None:
            self._set_warmup()
            return
        state, probs = self._predict(np.array([self.samples[-1]], dtype=float))
        label = self.state_labels.get(state, f"state_{state}")
        self._prediction_history.append(label)
        if len(self._prediction_history) < 10 or len(set(self._prediction_history)) != 1:
            self._set_warmup(state=state, probs=probs)
            return
        self._current_state = state
        self._current_probabilities = probs
        self._current_label = label

    def _set_warmup(self, state: int = -1, probs: list[float] | None = None) -> None:
        self._current_label = "warmup"
        self._current_state = state
        self._current_probabilities = probs or [1.0]

    def _needs_refit(self, now: float) -> bool:
        if self.model is None or now - self.last_fit_started_at >= self.fit_interval_seconds:
            return True
        if len(self.samples) >= 200:
            current = np.array(list(self.samples)[-100:], dtype=float)
            prior = np.array(list(self.samples)[-200:-100], dtype=float)
            if self._kl_divergence(current, prior) > 0.5:
                return True
        return False

    def _fit_model(self, matrix: np.ndarray) -> _FitResult:
        if GaussianHMM is None:
            return _FitResult(model="fallback", state_labels={0: "mean_reverting", 1: "trending", 2: "high_stress"})
        best_model = None
        best_bic = math.inf
        best_labels: dict[int, str] = {}
        for n_components in (2, 3, 4):
            for random_state in range(3):
                model = GaussianHMM(n_components=n_components, covariance_type="full", n_iter=500, random_state=random_state)
                model.fit(matrix)
                if not getattr(model.monitor_, "converged", True):
                    continue
                log_like = float(model.score(matrix))
                n_features = matrix.shape[1]
                params = n_components * n_components + 2 * n_components * n_features - 1
                bic = -2 * log_like + params * math.log(len(matrix))
                if bic < best_bic:
                    best_bic = bic
                    best_model = model
                    best_labels = self._label_states(model.means_)
        if best_model is None:
            return _FitResult(model="fallback", state_labels={0: "mean_reverting", 1: "trending", 2: "high_stress"})
        return _FitResult(model=best_model, state_labels=best_labels)

    def _label_states(self, means: np.ndarray) -> dict[int, str]:
        state_labels: dict[int, str] = {}
        vol_rank = np.argsort(means[:, 0])
        high_stress_state = int(vol_rank[-1])
        state_labels[high_stress_state] = "high_stress"
        remaining = [idx for idx in range(len(means)) if idx != high_stress_state]
        if remaining:
            trend_scores = {idx: abs(float(means[idx, 1])) for idx in remaining}
            trending_state = max(trend_scores, key=trend_scores.get)
            state_labels[trending_state] = "trending"
            for idx in remaining:
                if idx != trending_state:
                    state_labels[idx] = "mean_reverting"
        return state_labels

    def _predict(self, matrix: np.ndarray) -> tuple[int, list[float]]:
        if self.model == "fallback":
            latest = matrix[-1]
            if latest[0] > np.percentile(np.array(self.samples)[:, 0], 75):
                state = 2
            elif abs(latest[1]) > np.percentile(np.abs(np.array(self.samples)[:, 1]), 60):
                state = 1
            else:
                state = 0
            probs = [0.1, 0.1, 0.1]
            probs[state] = 0.8
            return state, probs
        assert GaussianHMM is not None
        model: GaussianHMM = self.model  # type: ignore[assignment]
        probs = model.predict_proba(matrix)[0].tolist()
        state = int(np.argmax(probs))
        return state, probs

    def _kl_divergence(self, current: np.ndarray, prior: np.ndarray) -> float:
        current_mu = current.mean(axis=0)
        prior_mu = prior.mean(axis=0)
        current_var = current.var(axis=0) + 1e-9
        prior_var = prior.var(axis=0) + 1e-9
        kl = 0.5 * np.sum((prior_var / current_var) + ((current_mu - prior_mu) ** 2) / current_var - 1 + np.log(current_var / prior_var))
        return float(max(kl, 0.0))

    def current(self) -> RegimeRecord:
        latest = self.samples[-1] if self.samples else [0.0, 0.0, 0.0]
        return RegimeRecord(
            label=self._current_label,
            state_id=self._current_state,
            probabilities=list(self._current_probabilities),
            features=list(latest),
            timestamp=utc_now(),
        )
