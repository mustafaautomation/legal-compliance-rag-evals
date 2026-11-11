"""Deterministic TF-IDF embeddings shared by FAISS and pgvector."""

from __future__ import annotations

from typing import cast

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class TfidfEmbedder:
    """Fit a TF-IDF space on the indexed clauses and L2-normalise vectors.

    The same fitted space is used for documents and queries, so retrieval does
    not call an external embedding API. Live chat providers are separate.
    """

    def __init__(self) -> None:
        self._vectorizer: TfidfVectorizer | None = None
        self.dimension = 0

    def fit(self, texts: list[str]) -> None:
        if len(texts) < 2:
            raise ValueError("Need at least two texts to fit embeddings")
        self._vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), norm="l2")
        matrix = self._vectorizer.fit_transform(texts)
        self.dimension = int(matrix.shape[1])

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        vectorizer = self._require_fit()
        matrix = vectorizer.transform(texts)
        vectors = np.asarray(matrix.toarray(), dtype=np.float32)
        return np.ascontiguousarray(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        row = self.embed_documents([text])[0]
        return cast(np.ndarray, row)

    def _require_fit(self) -> TfidfVectorizer:
        if self._vectorizer is None:
            raise RuntimeError("Embedder is not fit")
        return self._vectorizer
