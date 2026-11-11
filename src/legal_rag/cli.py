"""Command line for a single question."""

from __future__ import annotations

import argparse

from legal_rag.config import load_settings
from legal_rag.pipeline import build_pipeline


def main(argv: list[str] | None = None) -> int:
    """Answer one question and print the reply."""
    parser = argparse.ArgumentParser(description="Ask the Helios Ledger compliance index.")
    parser.add_argument("question", nargs="+", help="Question text")
    parser.add_argument("--provider", choices=["fake", "openai", "anthropic"], default="fake")
    parser.add_argument("--retriever", choices=["faiss", "pgvector"], default="faiss")
    parser.add_argument(
        "--variant",
        choices=["guarded", "no_guardrail", "bad_retriever"],
        default="guarded",
    )
    args = parser.parse_args(argv)
    pipeline = build_pipeline(
        load_settings(),
        variant=args.variant,
        provider_kind=args.provider,
        retriever_kind=args.retriever,
    )
    result = pipeline.answer(" ".join(args.question))
    print(result.response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
