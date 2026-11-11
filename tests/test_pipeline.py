"""Corpus, retrieval, and guardrail behaviour."""

from __future__ import annotations

from legal_rag.config import load_settings
from legal_rag.corpus import load_corpus
from legal_rag.embeddings import TfidfEmbedder
from legal_rag.evaluation.dataset import load_dataset
from legal_rag.pipeline import build_pipeline
from legal_rag.prompts import DISCLAIMER
from legal_rag.providers import (
    AnthropicChatProvider,
    GuardedExtractiveProvider,
    OpenAIChatProvider,
)
from legal_rag.retrieval import FaissRetriever, vector_literal
from legal_rag.types import Chunk, GenerationRequest, Retrieved


def test_corpus_size_and_gdpr_attribution() -> None:
    chunks = load_corpus()
    doc_ids = {chunk.doc_id for chunk in chunks}
    assert 15 <= len(doc_ids) <= 30
    gdpr = [chunk for chunk in chunks if chunk.doc_id.startswith("HL-REG-GDPR")]
    assert gdpr
    assert all("CELEX:32016R0679" in chunk.source for chunk in gdpr)
    assert all(
        chunk.license_name.startswith("CC0")
        for chunk in chunks
        if chunk.doc_id.startswith("HL-POL")
    )


def test_each_anchor_matches_one_chunk() -> None:
    chunks = load_corpus()
    for item in load_dataset():
        if not item.expects_retrieval:
            continue
        matches = [
            chunk
            for chunk in chunks
            if chunk.doc_id in item.reference_doc_ids
            and all(anchor in chunk.text for anchor in item.anchors)
        ]
        assert len(matches) == 1, item.id


def test_embeddings_are_deterministic_and_normalised() -> None:
    chunks = load_corpus()
    first = TfidfEmbedder()
    second = TfidfEmbedder()
    texts = [chunk.text for chunk in chunks]
    first.fit(texts)
    second.fit(texts)
    left = first.embed_documents(texts[:3])
    right = second.embed_documents(texts[:3])
    assert left.shape == right.shape
    assert (left == right).all()
    query = first.embed_query("customer invoices kept for six years")
    norm = float((query**2).sum()) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_faiss_retrieves_invoice_clause() -> None:
    chunks = load_corpus()
    retriever = FaissRetriever(chunks)
    hits = retriever.search("How long are customer invoices kept after the contract ends?", k=4)
    assert hits[0].chunk.doc_id == "HL-POL-004"
    assert "six years" in hits[0].chunk.text


def test_guarded_answer_cites_and_disclaims() -> None:
    settings = load_settings()
    pipeline = build_pipeline(settings, chunks=load_corpus())
    answer = pipeline.answer("How long are customer invoices kept after the contract ends?")
    assert "HL-POL-004 clause 3.1" in answer.response
    assert "six years" in answer.response
    assert DISCLAIMER in answer.response
    assert "I don't know" not in answer.response


def test_guarded_refuses_tax_question() -> None:
    settings = load_settings()
    pipeline = build_pipeline(settings, chunks=load_corpus())
    answer = pipeline.answer(
        "What Irish corporate tax rate should Helios pay for the 2026 financial year?"
    )
    assert "I don't know" in answer.response
    assert "will not speculate" in answer.response
    assert "not legal advice" in answer.response.lower()


def test_no_guardrail_omits_disclaimer_and_speculates() -> None:
    settings = load_settings()
    pipeline = build_pipeline(settings, variant="no_guardrail", chunks=load_corpus())
    answer = pipeline.answer(
        "What Irish corporate tax rate should Helios pay for the 2026 financial year?"
    )
    assert "not legal advice" not in answer.response.lower()
    assert "court would likely" in answer.response.lower()
    assert "Sources:" not in answer.response


def test_bad_retriever_misses_invoice_document() -> None:
    settings = load_settings()
    pipeline = build_pipeline(settings, variant="bad_retriever", chunks=load_corpus())
    answer = pipeline.answer("How long are customer invoices kept after the contract ends?")
    assert all(hit.chunk.doc_id == "HL-POL-018" for hit in answer.retrieved)
    assert "six years" not in answer.response


def test_vector_literal_and_pgvector_sql_shape() -> None:
    import numpy as np

    literal = vector_literal(np.array([0.25, -1.5], dtype=np.float32))
    assert literal == "[0.25000000,-1.50000000]"
    import inspect

    from legal_rag.retrieval import PgVectorRetriever

    source = inspect.getsource(PgVectorRetriever)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
    assert "embedding <=> %s::vector" in source


def test_openai_and_anthropic_providers_use_injected_clients() -> None:
    chunk = Chunk(
        chunk_id="HL-POL-004#3.1-1",
        doc_id="HL-POL-004",
        title="Retention",
        citation="HL-POL-004 clause 3.1",
        text="Clause 3.1\n\nInvoices are kept for six years.",
        source="synthetic",
        license_name="CC0-1.0",
    )
    request = GenerationRequest(
        question="How long are invoices kept?",
        contexts=[Retrieved(chunk, 0.5)],
        system_prompt="Cite the clause. This is not legal advice.",
    )

    class _Message:
        content = "Invoices are kept for six years. This is not legal advice."

    class _Choice:
        message = _Message()

    class _Completion:
        choices = [_Choice()]

    class _OpenAI:
        def __init__(self) -> None:
            self.chat = self
            self.completions = self
            self.kwargs: dict[str, object] = {}

        def create(self, **kwargs: object) -> _Completion:
            self.kwargs = kwargs
            return _Completion()

    openai_client = _OpenAI()
    text = OpenAIChatProvider(openai_client).generate(request)
    assert "six years" in text
    assert openai_client.kwargs["temperature"] == 0

    class _Block:
        text = "Cited answer. This is not legal advice."

    class _AnthropicMessage:
        content = [_Block()]

    class _Anthropic:
        def __init__(self) -> None:
            self.messages = self
            self.kwargs: dict[str, object] = {}

        def create(self, **kwargs: object) -> _AnthropicMessage:
            self.kwargs = kwargs
            return _AnthropicMessage()

    anthropic_client = _Anthropic()
    reply = AnthropicChatProvider(anthropic_client).generate(request)
    assert "not legal advice" in reply
    assert anthropic_client.kwargs["system"] == request.system_prompt


def test_extractive_provider_refuses_without_overlap() -> None:
    chunk = Chunk(
        chunk_id="HL-POL-018#1.1-1",
        doc_id="HL-POL-018",
        title="Subprocessors",
        citation="HL-POL-018 clause 1.1",
        text="Clause 1.1\n\nNorth Quay Hosting provides the application hosting service.",
        source="synthetic",
        license_name="CC0-1.0",
    )
    from legal_rag.prompts import GUARDED_SYSTEM

    provider = GuardedExtractiveProvider(min_term_overlap=3)
    reply = provider.generate(
        GenerationRequest(
            question="What Irish corporate tax rate should Helios pay for 2026?",
            contexts=[Retrieved(chunk, 0.2)],
            system_prompt=GUARDED_SYSTEM,
        )
    )
    assert reply.startswith("I don't know")
    assert "not legal advice" in reply.lower()
