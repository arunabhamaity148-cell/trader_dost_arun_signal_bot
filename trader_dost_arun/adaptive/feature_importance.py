from __future__ import annotations

from collections import defaultdict
from statistics import mean


class OnlineFeatureImportanceTracker:
    def __init__(self) -> None:
        self.success_values: dict[str, list[float]] = defaultdict(list)
        self.failure_values: dict[str, list[float]] = defaultdict(list)

    def update(self, feature_map: dict[str, float], outcome: int) -> None:
        target = self.success_values if outcome > 0 else self.failure_values
        for key, value in feature_map.items():
            target[key].append(float(value))
            if len(target[key]) > 1000:
                target[key].pop(0)

    def summary(self) -> dict[str, float]:
        importance: dict[str, float] = {}
        keys = set(self.success_values) | set(self.failure_values)
        for key in keys:
            success_mean = mean(self.success_values[key]) if self.success_values[key] else 0.0
            failure_mean = mean(self.failure_values[key]) if self.failure_values[key] else 0.0
            importance[key] = abs(success_mean - failure_mean)
        return dict(sorted(importance.items(), key=lambda item: item[1], reverse=True)[:20])
