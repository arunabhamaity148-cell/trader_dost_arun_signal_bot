from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

try:
    from hmmlearn.hmm import GaussianHMM
except Exception:  # noqa: BLE001
    GaussianHMM = None

from trader_dost_arun.core.models import RegimeRecord, utc_now

LOGGER = logging.getLogger(__name__)
FALLBACK_LABELS = {0: "mean_reverting", 1: "trending", 2: "high_stress"}


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
        self._last_fit_error: str | None = None

    def _is_valid_number(self, value: float | int) -> bool:
        return math.isfinite(float(value))

    def _validated_sample(self, vol: float, trend_strength: float, funding_regime: float) -> list[float] | None:
        sample = [float(vol), float(trend_strength), float(funding_regime)]
        if not all(self._is_valid_number(item) for item in sample):
            return None
        return sample

    async def observe(self, vol: float, trend_strength: float, funding_regime: float) -> None:
        sample = self._validated_sample(vol, trend_strength, funding_regime)
        if self._fit_task and self._fit_task.done():
            await self._consume_fit_task()
        if sample is None:
            self._set_warmup()
            return
        self.samples.append(sample)
        if len(self.samples) < self.min_samples:
            self._set_warmup()
            return
        now = time.monotonic()
        if self._needs_refit(now) and self._fit_task is None:
            self.last_fit_started_at = now
            matrix = self._sanitized_matrix(np.array(self.samples, dtype=float))
            if len(matrix) >= self.min_samples:
                self._fit_task = asyncio.create_task(asyncio.to_thread(self._fit_model, matrix), name="hmm-fit")
                self._fit_task.add_done_callback(self._handle_fit_completion)
        if self.model is None:
            self._set_warmup()
            return
        state, probs = self._predict(np.array([sample], dtype=float))
        label = self.state_labels.get(state, f"state_{state}")
        self._prediction_history.append(label)
        if len(self._prediction_history) < max(1, self.transition_confirmation_ticks) or len(set(list(self._prediction_history)[-self.transition_confirmation_ticks :])) != 1:
            self._set_warmup(state=state, probs=probs)
            return
        self._current_state = state
        self._current_probabilities = probs
        self._current_label = label

    async def _consume_fit_task(self) -> None:
        assert self._fit_task is not None
        task = self._fit_task
        self._fit_task = None
        try:
            result = await task
        except Exception as exc:  # noqa: BLE001
            self._last_fit_error = str(exc)
            LOGGER.warning("hmm refit failed: %s", exc)
            self.model = "fallback"
            self.state_labels = dict(FALLBACK_LABELS)
            return
        self.model = result.model
        self.state_labels = result.state_labels

    def _handle_fit_completion(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self._last_fit_error = str(exc)
            LOGGER.warning("hmm background fit failed: %s", exc)

    def _set_warmup(self, state: int = -1, probs: list[float] | None = None) -> None:
        self._current_label = "warmup"
        self._current_state = state
        self._current_probabilities = probs or [1.0]

    def _needs_refit(self, now: float) -> bool:
        if self._fit_task is not None:
            return False
        if self.model is None or now - self.last_fit_started_at >= self.fit_interval_seconds:
            return True
        if len(self.samples) >= 200:
            current = np.array(list(self.samples)[-100:], dtype=float)
            prior = np.array(list(self.samples)[-200:-100], dtype=float)
            if self._kl_divergence(current, prior) > 0.5:
                return True
        return False

    def _sanitized_matrix(self, matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            return matrix.reshape(0, 3)
        if matrix.ndim != 2:
            return np.empty((0, 3), dtype=float)
        finite_mask = np.all(np.isfinite(matrix), axis=1)
        sanitized = matrix[finite_mask]
        return sanitized

    def _fit_model(self, matrix: np.ndarray) -> _FitResult:
        matrix = self._sanitized_matrix(matrix)
        if len(matrix) < self.min_samples:
            return _FitResult(model="fallback", state_labels=dict(FALLBACK_LABELS))
        if GaussianHMM is None:
            return _FitResult(model="fallback", state_labels=dict(FALLBACK_LABELS))
        best_model = None
        best_bic = math.inf
        best_labels: dict[int, str] = {}
        for n_components in (2, 3, 4):
            for random_state in range(3):
                try:
                    model = GaussianHMM(n_components=n_components, covariance_type="full", n_iter=500, random_state=random_state)
                    model.fit(matrix)
                    if not getattr(model.monitor_, "converged", True):
                        continue
                    log_like = float(model.score(matrix))
                    if not math.isfinite(log_like):
                        continue
                    n_features = matrix.shape[1]
                    params = n_components * n_components + 2 * n_components * n_features - 1
                    bic = -2 * log_like + params * math.log(len(matrix))
                    if bic < best_bic:
                        best_bic = bic
                        best_model = model
                        best_labels = self._label_states(model.means_)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("hmm candidate failed: %s", exc)
                    continue
        if best_model is None:
            return _FitResult(model="fallback", state_labels=dict(FALLBACK_LABELS))
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

    def _fallback_state(self, latest: np.ndarray) -> tuple[int, list[float]]:
        if len(self.samples) < 10:
            return 0, [0.8, 0.1, 0.1]
        sample_matrix = np.array(self.samples, dtype=float)
        if latest[0] > np.percentile(sample_matrix[:, 0], 75):
            state = 2
        elif abs(latest[1]) > np.percentile(np.abs(sample_matrix[:, 1]), 60):
            state = 1
        else:
            state = 0
        probs = [0.1, 0.1, 0.1]
        probs[state] = 0.8
        return state, probs

    def _predict(self, matrix: np.ndarray) -> tuple[int, list[float]]:
        if not np.isfinite(matrix).all():
            return 0, [1.0]
        if self.model == "fallback":
            return self._fallback_state(matrix[-1])
        assert GaussianHMM is not None
        model: GaussianHMM = self.model  # type: ignore[assignment]
        try:
            probs = model.predict_proba(matrix)[0].tolist()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("hmm prediction failed, using fallback regime: %s", exc)
            self.model = "fallback"
            self.state_labels = dict(FALLBACK_LABELS)
            return self._fallback_state(matrix[-1])
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
