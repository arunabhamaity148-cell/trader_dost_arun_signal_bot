from __future__ import annotations

import asyncio
from collections import OrderedDict
from functools import lru_cache
from threading import RLock

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001
    SentenceTransformer = None

from sklearn.feature_extraction.text import TfidfVectorizer


class SemanticTextEmbedder:
    def __init__(self, similarity_cache_size: int = 2048) -> None:
        self._tfidf = TfidfVectorizer()
        self._similarity_cache_size = max(16, similarity_cache_size)
        self._similarity_cache: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._lock = RLock()

    @lru_cache(maxsize=1)
    def _model(self):
        return SentenceTransformer("all-MiniLM-L6-v2") if SentenceTransformer is not None else None

    async def warmup(self) -> None:
        """Load the sentence-transformer model in a worker thread ahead of time.

        Without this, the model is lazily constructed on the first call to
        similarity(), which happens the first time two news items need
        deduplicating. In production that first call landed in the same
        startup window as the initial websocket snapshot flood (see the
        `sentence_transformers.SentenceTransformer Load pretrained ...` log
        line appearing seconds after connect), competing for CPU with the
        event loop right when the ingress queue is under the most pressure
        and contributing to the large one-time burst of dropped/coalesced
        snapshots. Calling this once during NewsGuard.start(), before any
        connectors are live, moves that one-time cost out of the hot path.
        """
        await asyncio.to_thread(self._model)

    def cache_size(self) -> int:
        with self._lock:
            return len(self._similarity_cache)

    def _cache_key(self, left: str, right: str) -> tuple[str, str]:
        return tuple(sorted((left.strip(), right.strip())))

    def _get_cached(self, key: tuple[str, str]) -> float | None:
        with self._lock:
            value = self._similarity_cache.get(key)
            if value is None:
                return None
            self._similarity_cache.move_to_end(key)
            return value

    def _set_cached(self, key: tuple[str, str], value: float) -> None:
        with self._lock:
            self._similarity_cache[key] = value
            self._similarity_cache.move_to_end(key)
            while len(self._similarity_cache) > self._similarity_cache_size:
                self._similarity_cache.popitem(last=False)

    def similarity(self, left: str, right: str) -> float:
        key = self._cache_key(left, right)
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        score = 0.0
        model = self._model()
        if model is not None:
            try:
                embeddings = model.encode([left, right], normalize_embeddings=True, show_progress_bar=False)
                score = float(np.dot(embeddings[0], embeddings[1]))
                self._set_cached(key, score)
                return score
            except Exception:  # noqa: BLE001
                pass
        matrix = self._tfidf.fit_transform([left, right]).toarray()
        denom = np.linalg.norm(matrix[0]) * np.linalg.norm(matrix[1])
        score = float(np.dot(matrix[0], matrix[1]) / denom) if denom else 0.0
        self._set_cached(key, score)
        return score
