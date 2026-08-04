from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import roc_curve
from sklearn.preprocessing import StandardScaler

try:
    from lightgbm import LGBMClassifier
except Exception:  # noqa: BLE001
    LGBMClassifier = None

try:
    import shap
except Exception:  # noqa: BLE001
    shap = None


@dataclass(slots=True)
class StrategyMetaModel:
    scaler: StandardScaler = field(default_factory=lambda: StandardScaler(with_mean=False))
    fallback: SGDClassifier = field(default_factory=lambda: SGDClassifier(loss="log_loss", max_iter=1000, tol=1e-3, random_state=42))
    model: Any | None = None
    calibrator: IsotonicRegression | None = None
    threshold: float = 0.5
    is_fitted: bool = False
    top_features: list[tuple[str, float]] = field(default_factory=list)


class MetaLabelModel:
    """Per-strategy meta-label model with LightGBM primary and SGD fallback."""

    def __init__(self, threshold: float = 0.55) -> None:
        self.threshold = threshold
        self.models: dict[str, StrategyMetaModel] = {"global": StrategyMetaModel(threshold=threshold)}
        self._is_fitted = False

    def _get_model(self, strategy: str) -> StrategyMetaModel:
        if strategy not in self.models:
            self.models[strategy] = StrategyMetaModel(threshold=self.threshold)
        return self.models[strategy]

    def fit_strategy(self, strategy: str, features: list[list[float]], labels: list[int], feature_names: list[str] | None = None) -> None:
        if len(features) < 20 or len(set(labels)) < 2:
            self.partial_fit(features, labels, strategy=strategy)
            return
        model_state = self._get_model(strategy)
        x = np.asarray(features, dtype=float)
        y = np.asarray(labels, dtype=int)
        split = max(int(len(x) * 0.8), 1)
        x_train, x_val = x[:split], x[split:]
        y_train, y_val = y[:split], y[split:]
        model_state.scaler.fit(x_train)
        x_train_s = model_state.scaler.transform(x_train)
        x_val_s = model_state.scaler.transform(x_val) if len(x_val) else x_train_s
        if LGBMClassifier is not None:
            model_state.model = LGBMClassifier(
                n_estimators=80,
                learning_rate=0.05,
                max_depth=4,
                random_state=42,
                min_child_samples=10,
                subsample=0.9,
                colsample_bytree=0.9,
                verbose=-1,
            )
            model_state.model.fit(x_train_s, y_train)
            probs = model_state.model.predict_proba(x_val_s)[:, 1]
        else:
            model_state.fallback.fit(x_train_s, y_train)
            probs = model_state.fallback.predict_proba(x_val_s)[:, 1]
        if len(set(y_val.tolist() if len(y_val) else y_train.tolist())) >= 2:
            y_ref = y_val if len(y_val) else y_train
            model_state.calibrator = IsotonicRegression(out_of_bounds="clip")
            model_state.calibrator.fit(probs, y_ref)
            calibrated = model_state.calibrator.transform(probs)
            fpr, tpr, thresholds = roc_curve(y_ref, calibrated)
            j = tpr - fpr
            model_state.threshold = float(thresholds[int(np.argmax(j))]) if len(thresholds) else self.threshold
        self._update_feature_importance(model_state, x_train_s, feature_names or [f"f{i}" for i in range(x.shape[1])])
        model_state.is_fitted = True
        self._is_fitted = True

    def _update_feature_importance(self, model_state: StrategyMetaModel, x: np.ndarray, feature_names: list[str]) -> None:
        importance: list[tuple[str, float]] = []
        if shap is not None and model_state.model is not None:
            try:
                explainer = shap.TreeExplainer(model_state.model)
                values = np.abs(explainer.shap_values(x[: min(len(x), 64)]))
                if isinstance(values, list):
                    values = values[-1]
                scores = np.asarray(values).mean(axis=0)
                importance = sorted(zip(feature_names, scores.tolist(), strict=False), key=lambda item: item[1], reverse=True)[:10]
            except Exception:  # noqa: BLE001
                importance = []
        if not importance and hasattr(model_state.fallback, "coef_"):
            coef = np.abs(model_state.fallback.coef_[0]) if getattr(model_state.fallback, "coef_", None) is not None else np.zeros(len(feature_names))
            importance = sorted(zip(feature_names, coef.tolist(), strict=False), key=lambda item: item[1], reverse=True)[:10]
        model_state.top_features = [(name, float(score)) for name, score in importance]

    def partial_fit(self, features: list[list[float]], labels: list[int], strategy: str = "global") -> None:
        if not features:
            return
        model_state = self._get_model(strategy)
        x = np.asarray(features, dtype=float)
        y = np.asarray(labels, dtype=int)
        model_state.scaler.partial_fit(x)
        x_scaled = model_state.scaler.transform(x)
        if not model_state.is_fitted:
            model_state.fallback.partial_fit(x_scaled, y, classes=np.array([0, 1]))
        else:
            model_state.fallback.partial_fit(x_scaled, y)
        model_state.is_fitted = True
        self._is_fitted = True

    def predict_probability(self, feature_row: list[float], strategy: str = "global") -> float:
        model_state = self.models.get(strategy) or self.models.get("global")
        if model_state is None or not model_state.is_fitted:
            return 0.5
        x_scaled = model_state.scaler.transform(np.asarray([feature_row], dtype=float))
        if model_state.model is not None:
            prob = float(model_state.model.predict_proba(x_scaled)[0][1])
        else:
            prob = float(model_state.fallback.predict_proba(x_scaled)[0][1])
        if model_state.calibrator is not None:
            prob = float(model_state.calibrator.transform([prob])[0])
        return max(0.0, min(1.0, prob))

    def allow(self, feature_row: list[float], strategy: str = "global") -> bool:
        model_state = self.models.get(strategy) or self.models.get("global")
        threshold = model_state.threshold if model_state is not None else self.threshold
        return self.predict_probability(feature_row, strategy=strategy) >= threshold

    def save(self, path: Path) -> None:
        payload: dict[str, Any] = {
            strategy: {
                "scaler": state.scaler,
                "fallback": state.fallback,
                "model": state.model,
                "calibrator": state.calibrator,
                "threshold": state.threshold,
                "is_fitted": state.is_fitted,
                "top_features": state.top_features,
            }
            for strategy, state in self.models.items()
        }
        joblib.dump(payload, path)

    def export_feature_importance(self, path: Path) -> None:
        serialisable = {strategy: state.top_features for strategy, state in self.models.items() if state.top_features}
        path.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")
