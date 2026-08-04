from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from trader_dost_arun.ml.purged_kfold import PurgedKFold, combinatorial_purged_splits

try:
    from lightgbm import LGBMClassifier
except Exception:  # noqa: BLE001
    LGBMClassifier = None


@dataclass(slots=True)
class FoldMetric:
    auc: float
    logloss: float
    brier: float
    precision_top20: float
    recall_top20: float


@dataclass(slots=True)
class WalkForwardReport:
    folds: list[FoldMetric] = field(default_factory=list)
    calibration_curve: list[dict[str, float]] = field(default_factory=list)


class WalkForwardMetaLabeler:
    def __init__(self, embargo: int = 30, min_samples: int = 1000, cpcv: bool = False) -> None:
        self.embargo = embargo
        self.min_samples = min_samples
        self.cpcv = cpcv

    def train(self, x: np.ndarray, y: np.ndarray, feature_names: list[str], model_path: Path | None = None, calibration_json_path: Path | None = None) -> WalkForwardReport | None:
        if len(x) < self.min_samples or len(np.unique(y)) < 2:
            return None
        folds = combinatorial_purged_splits(x, embargo=self.embargo) if self.cpcv else PurgedKFold(embargo=self.embargo).split(x)
        report = WalkForwardReport()
        all_probs: list[float] = []
        all_truths: list[int] = []
        for fold in folds:
            x_train, y_train = x[fold.train_idx], y[fold.train_idx]
            x_test, y_test = x[fold.test_idx], y[fold.test_idx]
            if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
                continue
            scaler = StandardScaler(with_mean=False)
            x_train_s = scaler.fit_transform(x_train)
            x_test_s = scaler.transform(x_test)
            if LGBMClassifier is not None:
                model = LGBMClassifier(n_estimators=80, learning_rate=0.05, max_depth=4, random_state=42, verbose=-1)
                model.fit(x_train_s, y_train)
                probs = model.predict_proba(x_test_s)[:, 1]
            else:
                model = SGDClassifier(loss="log_loss", max_iter=1500, tol=1e-3, random_state=42)
                model.fit(x_train_s, y_train)
                probs = model.predict_proba(x_test_s)[:, 1]
            threshold = np.quantile(probs, 0.8)
            selected = probs >= threshold
            precision_top20 = float((y_test[selected] == 1).mean()) if selected.any() else 0.0
            recall_top20 = float((y_test[selected] == 1).sum() / max((y_test == 1).sum(), 1)) if selected.any() else 0.0
            report.folds.append(
                FoldMetric(
                    auc=float(roc_auc_score(y_test, probs)),
                    logloss=float(log_loss(y_test, probs, labels=[0, 1])),
                    brier=float(brier_score_loss(y_test, probs)),
                    precision_top20=precision_top20,
                    recall_top20=recall_top20,
                )
            )
            all_probs.extend(probs.tolist())
            all_truths.extend(y_test.tolist())
        if not report.folds:
            return None
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(all_probs, all_truths)
        xs = np.linspace(0.0, 1.0, 11)
        ys = iso.transform(xs)
        report.calibration_curve = [{"pred": float(xv), "actual": float(yv)} for xv, yv in zip(xs, ys)]
        if calibration_json_path is not None:
            calibration_json_path.parent.mkdir(parents=True, exist_ok=True)
            calibration_json_path.write_text(json.dumps(report.calibration_curve, indent=2), encoding="utf-8")
        scaler = StandardScaler(with_mean=False)
        x_scaled = scaler.fit_transform(x)
        if LGBMClassifier is not None:
            final_model = LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, random_state=42, verbose=-1)
        else:
            final_model = SGDClassifier(loss="log_loss", max_iter=1500, tol=1e-3, random_state=42)
        final_model.fit(x_scaled, y)
        if model_path is not None:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": final_model, "scaler": scaler, "feature_names": feature_names, "calibrator": iso}, model_path)
        return report
