"""Shared data types for the RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """One operative clause from the corpus."""

    chunk_id: str
    doc_id: str
    title: str
    citation: str
    text: str
    source: str
    license_name: str


@dataclass(frozen=True)
class Retrieved:
    """A chunk returned by a retriever, with a similarity score."""

    chunk: Chunk
    score: float


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs handed to a chat provider."""

    question: str
    contexts: list[Retrieved]
    system_prompt: str


@dataclass(frozen=True)
class Answer:
    """A pipeline answer plus the contexts that were shown to the provider."""

    question: str
    response: str
    retrieved: list[Retrieved]
    variant: str
