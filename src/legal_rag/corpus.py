"""Load markdown policies and regulation excerpts into clause chunks."""

from __future__ import annotations

import re
from pathlib import Path

from legal_rag.config import CORPUS_DIR
from legal_rag.types import Chunk

_HEADER_KEYS = ("Doc-ID", "Title", "Source", "License", "Instrument")
_CLAUSE_RE = re.compile(r"^## Clause ([0-9]+(?:\.[0-9]+)?) (.+)$")
_ARTICLE_RE = re.compile(r"^## Article ([0-9]+)\b(.*)$")


def load_corpus(directory: Path = CORPUS_DIR) -> list[Chunk]:
    """Index every `##` clause or article in the corpus directory."""
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No markdown documents in {directory}")
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for path in paths:
        for chunk in _parse_document(path):
            if chunk.chunk_id in seen:
                raise ValueError(f"Duplicate chunk id {chunk.chunk_id}")
            seen.add(chunk.chunk_id)
            chunks.append(chunk)
    chunks.sort(key=lambda chunk: chunk.chunk_id)
    return chunks


def _parse_document(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    header, body = _split_header(text, path)
    doc_id = header["Doc-ID"]
    instrument = header.get("Instrument", "")
    sections = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    chunks: list[Chunk] = []
    seen_suffixes: dict[str, int] = {}
    for section in sections:
        section = section.strip()
        if not section.startswith("## "):
            continue
        heading, _, remainder = section.partition("\n")
        clause_body = remainder.strip()
        if not clause_body:
            raise ValueError(f"{path.name} has an empty section: {heading}")
        citation, suffix = _citation(doc_id, instrument, heading, path)
        seen_suffixes[suffix] = seen_suffixes.get(suffix, 0) + 1
        chunk_id = f"{doc_id}#{suffix}-{seen_suffixes[suffix]}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                title=header["Title"],
                citation=citation,
                text=f"{heading[3:].strip()}\n\n{clause_body}",
                source=header["Source"],
                license_name=header["License"],
            )
        )
    if len(chunks) < 2:
        raise ValueError(f"{path.name} must contain at least two clauses")
    return chunks


def _split_header(text: str, path: Path) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    header: dict[str, str] = {}
    body_start: int | None = None
    for line_number, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            body_start = line_number
            break
        if ":" not in line:
            raise ValueError(f"{path.name} has a header line without a colon: {line}")
        key, value = line.split(":", 1)
        header[key.strip()] = value.strip()
    if body_start is None:
        raise ValueError(f"{path.name} is missing a title heading")
    missing = [key for key in _HEADER_KEYS if key not in header and key != "Instrument"]
    if missing:
        raise ValueError(f"{path.name} is missing header fields: {', '.join(missing)}")
    return header, "\n".join(lines[body_start:])


def _citation(doc_id: str, instrument: str, heading: str, path: Path) -> tuple[str, str]:
    clause_match = _CLAUSE_RE.match(heading)
    if clause_match:
        number = clause_match.group(1)
        return f"{doc_id} clause {number}", number
    article_match = _ARTICLE_RE.match(heading)
    if article_match:
        number = article_match.group(1)
        label = instrument or "GDPR"
        return f"{label} Article {number} ({doc_id})", number
    raise ValueError(f"{path.name} has an unsupported heading: {heading}")
