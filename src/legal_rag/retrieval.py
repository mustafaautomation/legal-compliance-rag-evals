"""FAISS retrieval, a pgvector retriever, and the deliberately broken variant."""

from __future__ import annotations

from typing import Protocol

import faiss
import numpy as np

from legal_rag.embeddings import TfidfEmbedder
from legal_rag.types import Chunk, Retrieved


class Retriever(Protocol):
    """Search interface used by the pipeline."""

    def search(self, query: str, k: int) -> list[Retrieved]:
        """Return up to `k` chunks for a query."""


def vector_literal(vector: np.ndarray) -> str:
    """Format a vector for a pgvector cast."""
    return "[" + ",".join(f"{float(value):.8f}" for value in vector.tolist()) + "]"


class FaissRetriever:
    """In-memory inner-product search over L2-normalised TF-IDF vectors."""

    def __init__(self, chunks: list[Chunk], embedder: TfidfEmbedder | None = None) -> None:
        if not chunks:
            raise ValueError("Cannot index an empty corpus")
        self.chunks = list(chunks)
        self.embedder = embedder or TfidfEmbedder()
        self.embedder.fit([chunk.text for chunk in self.chunks])
        vectors = self.embedder.embed_documents([chunk.text for chunk in self.chunks])
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        self._index = index

    def search(self, query: str, k: int) -> list[Retrieved]:
        if k < 1:
            raise ValueError("k must be positive")
        query_vector = np.ascontiguousarray(
            self.embedder.embed_query(query).reshape(1, -1), dtype=np.float32
        )
        scores, indices = self._index.search(query_vector, min(k, len(self.chunks)))
        hits: list[Retrieved] = []
        for score, index in zip(scores[0], indices[0], strict=True):
            if int(index) < 0:
                continue
            hits.append(Retrieved(self.chunks[int(index)], float(score)))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return hits[:k]


class FixedDocRetriever:
    """Ignore the query and return clauses from one document.

    This is the broken retriever used to prove the eval gate fails.
    """

    def __init__(self, chunks: list[Chunk], doc_id: str) -> None:
        self._fixed = [chunk for chunk in chunks if chunk.doc_id == doc_id]
        if not self._fixed:
            raise ValueError(f"No chunks for {doc_id}")

    def search(self, query: str, k: int) -> list[Retrieved]:
        del query
        if k < 1:
            raise ValueError("k must be positive")
        return [Retrieved(chunk, 0.0) for chunk in self._fixed[:k]]


class PgVectorRetriever:
    """Store the same TF-IDF vectors in Postgres and search with cosine distance.

    Requires the pgvector extension. Tests use `FaissRetriever` and do not
    need this class.
    """

    def __init__(
        self, dsn: str, chunks: list[Chunk], embedder: TfidfEmbedder | None = None
    ) -> None:
        import psycopg

        if not chunks:
            raise ValueError("Cannot index an empty corpus")
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.embedder = embedder or TfidfEmbedder()
        self.embedder.fit([chunk.text for chunk in chunks])
        vectors = self.embedder.embed_documents([chunk.text for chunk in chunks])
        dimension = int(vectors.shape[1])
        self._conn = psycopg.connect(dsn)
        with self._conn.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute("DROP TABLE IF EXISTS chunks")
            cursor.execute(
                f"CREATE TABLE chunks ("
                f"chunk_id text PRIMARY KEY, "
                f"doc_id text NOT NULL, "
                f"citation text NOT NULL, "
                f"content text NOT NULL, "
                f"embedding vector({dimension}) NOT NULL)"
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                cursor.execute(
                    "INSERT INTO chunks (chunk_id, doc_id, citation, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s::vector)",
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.citation,
                        chunk.text,
                        vector_literal(vector),
                    ),
                )
        self._conn.commit()

    def search(self, query: str, k: int) -> list[Retrieved]:
        if k < 1:
            raise ValueError("k must be positive")
        literal = vector_literal(self.embedder.embed_query(query))
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score "
                "FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (literal, literal, k),
            )
            rows = cursor.fetchall()
        hits = [Retrieved(self._chunks[str(chunk_id)], float(score)) for chunk_id, score in rows]
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return hits

    def close(self) -> None:
        self._conn.close()
