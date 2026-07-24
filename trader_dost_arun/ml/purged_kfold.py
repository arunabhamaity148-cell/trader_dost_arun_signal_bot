from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class PurgedFold:
    train_idx: np.ndarray
    test_idx: np.ndarray


class PurgedKFold:
    def __init__(self, n_splits: int = 5, embargo: int = 5) -> None:
        self.n_splits = n_splits
        self.embargo = embargo

    def split(self, x: np.ndarray) -> list[PurgedFold]:
        n = len(x)
        fold_size = max(n // self.n_splits, 1)
        folds: list[PurgedFold] = []
        for idx in range(self.n_splits):
            test_start = idx * fold_size
            test_end = n if idx == self.n_splits - 1 else min(n, (idx + 1) * fold_size)
            purge_start = max(0, test_start - self.embargo)
            purge_end = min(n, test_end + self.embargo)
            train_idx = np.array([i for i in range(n) if i < purge_start or i >= purge_end], dtype=int)
            test_idx = np.arange(test_start, test_end, dtype=int)
            if len(train_idx) and len(test_idx):
                folds.append(PurgedFold(train_idx=train_idx, test_idx=test_idx))
        return folds


def combinatorial_purged_splits(x: np.ndarray, n_splits: int = 5, embargo: int = 5, test_groups: int = 2) -> list[PurgedFold]:
    base = PurgedKFold(n_splits=n_splits, embargo=embargo).split(x)
    if test_groups <= 1 or len(base) < test_groups:
        return base
    combined: list[PurgedFold] = []
    for start in range(0, len(base) - test_groups + 1):
        test_idx = np.concatenate([base[i].test_idx for i in range(start, start + test_groups)])
        train_idx = np.array(sorted(set(range(len(x))) - set(test_idx.tolist())), dtype=int)
        if len(train_idx):
            combined.append(PurgedFold(train_idx=train_idx, test_idx=test_idx))
    return combined
