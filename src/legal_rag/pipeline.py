"""Assemble a retriever and a chat provider into a RAG pipeline."""

from __future__ import annotations

import os

from legal_rag.config import Settings
from legal_rag.corpus import load_corpus
from legal_rag.prompts import system_prompt_for
from legal_rag.providers import ChatProvider, build_chat_provider
from legal_rag.retrieval import FaissRetriever, FixedDocRetriever, PgVectorRetriever, Retriever
from legal_rag.types import Answer, Chunk, GenerationRequest


class RagPipeline:
    """Retrieve clauses and generate an answer for one variant."""

    def __init__(
        self, retriever: Retriever, provider: ChatProvider, variant: str, top_k: int
    ) -> None:
        self.retriever = retriever
        self.provider = provider
        self.variant = variant
        self.top_k = top_k

    def answer(self, question: str) -> Answer:
        retrieved = self.retriever.search(question, self.top_k)
        response = self.provider.generate(
            GenerationRequest(
                question=question,
                contexts=retrieved,
                system_prompt=system_prompt_for(self.variant),
            )
        )
        return Answer(
            question=question,
            response=response,
            retrieved=retrieved,
            variant=self.variant,
        )


def build_pipeline(
    settings: Settings,
    variant: str = "guarded",
    provider_kind: str = "fake",
    retriever_kind: str = "faiss",
    chunks: list[Chunk] | None = None,
) -> RagPipeline:
    """Build the demo pipeline. `variant` selects guardrails and the retriever."""
    indexed = chunks if chunks is not None else load_corpus()
    if variant == "bad_retriever":
        retriever: Retriever = FixedDocRetriever(indexed, settings.bad_retriever_doc_id)
    elif retriever_kind == "faiss":
        retriever = FaissRetriever(indexed)
    elif retriever_kind == "pgvector":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        retriever = PgVectorRetriever(dsn, indexed)
    else:
        raise ValueError(f"Unknown retriever: {retriever_kind}")
    provider = build_chat_provider(provider_kind, variant, settings.min_term_overlap)
    return RagPipeline(retriever, provider, variant, settings.top_k)
