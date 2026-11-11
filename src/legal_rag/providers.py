"""Chat providers: deterministic offline models, OpenAI, and Anthropic."""

from __future__ import annotations

import os
import re
from typing import Any, Protocol

from legal_rag.prompts import DISCLAIMER
from legal_rag.types import GenerationRequest, Retrieved

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "and",
        "or",
        "for",
        "in",
        "on",
        "is",
        "are",
        "was",
        "be",
        "by",
        "with",
        "that",
        "this",
        "it",
        "as",
        "at",
        "from",
        "does",
        "do",
        "how",
        "what",
        "when",
        "where",
        "who",
        "which",
        "may",
        "can",
        "should",
        "about",
        "into",
        "not",
        "no",
        "yes",
        "confirm",
        "helios",
        "ledger",
        "ltd",
        "our",
        "your",
        "after",
        "before",
        "within",
        "only",
        "any",
        "under",
        "than",
        "then",
        "them",
        "they",
        "their",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "please",
        "tell",
        "give",
        "did",
        "been",
        "being",
        "such",
        "also",
        "must",
        "over",
        "its",
        "his",
        "her",
        "data",
        "personal",
        "protection",
        "staff",
    }
)


class ChatProvider(Protocol):
    """Generate a reply from a question and retrieved clauses."""

    def generate(self, request: GenerationRequest) -> str:
        """Return the assistant text."""


def content_terms(text: str) -> set[str]:
    """Lowercase content words used by the offline guarded generator."""
    return {
        word for word in _WORD_RE.findall(text.lower()) if len(word) > 3 and word not in _STOPWORDS
    }


def render_user_message(request: GenerationRequest) -> str:
    """Render retrieved clauses into the user message live providers send."""
    if not request.contexts:
        clauses = "(no clauses retrieved)"
    else:
        blocks = [
            f"Citation: {item.chunk.citation}\n{item.chunk.text}" for item in request.contexts
        ]
        clauses = "\n\n---\n\n".join(blocks)
    return f"Question:\n{request.question}\n\nClauses:\n{clauses}"


class GuardedExtractiveProvider:
    """Quote the best overlapping clause, or refuse.

    This is the deterministic offline stand-in for the guarded prompt. It does
    not read gold labels. It only sees the question and the retrieved clauses.
    """

    def __init__(self, min_term_overlap: int) -> None:
        if min_term_overlap < 1:
            raise ValueError("min_term_overlap must be positive")
        self._min_term_overlap = min_term_overlap

    def generate(self, request: GenerationRequest) -> str:
        if "will not speculate" not in request.system_prompt:
            raise ValueError("Guarded provider requires the guarded system prompt")
        chosen = _best_supported_clause(request, self._min_term_overlap)
        if chosen is None:
            return (
                "I don't know. The indexed policies and regulation excerpts do not "
                "answer this, and I will not speculate beyond those documents.\n\n"
                f"{DISCLAIMER}"
            )
        return (
            "Based only on the indexed documents:\n\n"
            f"{chosen.chunk.text}\n\n"
            f"Sources: {chosen.chunk.citation}.\n\n"
            f"{DISCLAIMER}"
        )


class NoGuardrailProvider:
    """Follow the broken prompt: no citation, no disclaimer, speculate."""

    def generate(self, request: GenerationRequest) -> str:
        if "rely on this as legal advice" not in request.system_prompt:
            raise ValueError("No-guardrail provider requires the no-guardrail system prompt")
        if request.contexts:
            body = request.contexts[0].chunk.text
        else:
            body = "There is no indexed clause on this point."
        return (
            f"{body}\n\n"
            "A court would likely rule in your favour on this point. "
            "You should rely on this as legal advice."
        )


class OpenAIChatProvider:
    """OpenAI chat completions behind the provider interface."""

    def __init__(self, client: Any, model: str = "gpt-4o-mini") -> None:
        self._client = client
        self._model = model

    def generate(self, request: GenerationRequest) -> str:
        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": render_user_message(request)},
            ],
        )
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty message")
        return str(content)


class AnthropicChatProvider:
    """Anthropic messages behind the provider interface."""

    def __init__(self, client: Any, model: str = "claude-3-5-haiku-latest") -> None:
        self._client = client
        self._model = model

    def generate(self, request: GenerationRequest) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=800,
            temperature=0,
            system=request.system_prompt,
            messages=[{"role": "user", "content": render_user_message(request)}],
        )
        parts: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if not parts:
            raise RuntimeError("Anthropic returned an empty message")
        return "".join(parts)


def build_chat_provider(kind: str, variant: str, min_term_overlap: int) -> ChatProvider:
    """Construct a chat provider. Live providers read API keys from the environment."""
    if kind == "fake":
        if variant == "no_guardrail":
            return NoGuardrailProvider()
        return GuardedExtractiveProvider(min_term_overlap)
    if kind == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        from openai import OpenAI

        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIChatProvider(OpenAI(api_key=key), model)
    if kind == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        import anthropic

        model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        return AnthropicChatProvider(anthropic.Anthropic(api_key=key), model)
    raise ValueError(f"Unknown provider: {kind}")


def _best_supported_clause(request: GenerationRequest, minimum: int) -> Retrieved | None:
    question_terms = content_terms(request.question)
    best: Retrieved | None = None
    best_overlap = 0
    for retrieved in request.contexts:
        overlap = len(question_terms & content_terms(retrieved.chunk.text))
        if overlap > best_overlap or (
            overlap == best_overlap and best is not None and retrieved.score > best.score
        ):
            best = retrieved
            best_overlap = overlap
        elif overlap == best_overlap and best is None:
            best = retrieved
            best_overlap = overlap
    if best is None or best_overlap < minimum:
        return None
    return best
