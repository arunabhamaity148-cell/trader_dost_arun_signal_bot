from __future__ import annotations

from functools import lru_cache

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001
    SentenceTransformer = None

from sklearn.feature_extraction.text import TfidfVectorizer


class SemanticTextEmbedder:
    def __init__(self) -> None:
        self._tfidf = TfidfVectorizer()

    @lru_cache(maxsize=1)
    def _model(self):
        return SentenceTransformer("all-MiniLM-L6-v2") if SentenceTransformer is not None else None

    def similarity(self, left: str, right: str) -> float:
        model = self._model()
        if model is not None:
            try:
                embeddings = model.encode([left, right], normalize_embeddings=True)
                return float(np.dot(embeddings[0], embeddings[1]))
            except Exception:  # noqa: BLE001
                pass
        matrix = self._tfidf.fit_transform([left, right]).toarray()
        denom = np.linalg.norm(matrix[0]) * np.linalg.norm(matrix[1])
        return float(np.dot(matrix[0], matrix[1]) / denom) if denom else 0.0
