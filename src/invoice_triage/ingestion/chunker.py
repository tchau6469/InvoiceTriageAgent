"""Heading-aware chunks that retain complete clauses and Markdown tables."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from invoice_triage.domain import DocumentChunk, SourceDocument


class DocumentChunkError(ValueError):
    """A parsed document cannot be divided into useful retrieval sections."""


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NON_SLUG_CHARACTER = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _Section:
    heading: str
    body: str


def chunk_markdown_document(document: SourceDocument) -> tuple[DocumentChunk, ...]:
    """Create one chunk per H2 section plus a non-empty document overview."""

    sections = _heading_sections(document)
    if not sections:
        raise DocumentChunkError(f"{document.source_path}: no chunkable content")

    slug_counts: dict[str, int] = {}
    chunks: list[DocumentChunk] = []
    for ordinal, section in enumerate(sections):
        base_slug = _slugify(section.heading)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        suffix = "" if slug_counts[base_slug] == 1 else f"-{slug_counts[base_slug]}"
        chunk_id = f"{document.document_id}:{base_slug}{suffix}"
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                document_type=document.document_type,
                section=section.heading,
                ordinal=ordinal,
                content=section.body,
                source_path=document.source_path,
                status=document.status,
                vendor_id=document.vendor_id,
                category=document.category,
                effective_date=document.effective_date,
                expiration_date=document.expiration_date,
                metadata={**document.metadata, "document_title": document.title},
            )
        )
    return tuple(chunks)


def embedding_text(chunk: DocumentChunk) -> str:
    """Return the versioned text recipe embedded for document retrieval."""

    title = chunk.metadata.get("document_title")
    if not isinstance(title, str) or not title.strip():
        raise DocumentChunkError(f"{chunk.chunk_id}: document_title metadata is required")
    return f"{title.strip()}\n\n{chunk.section}\n\n{chunk.content.strip()}"


def _heading_sections(document: SourceDocument) -> list[_Section]:
    lines = document.content.splitlines()
    overview: list[str] = []
    sections: list[_Section] = []
    heading: str | None = None
    body: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING_PATTERN.match(line)

        if match and len(match.group(1)) == 1:
            # The parser already validated the sole H1; it is represented by
            # document_title metadata rather than repeated in every body.
            continue
        if match and len(match.group(1)) == 2:
            if heading is not None:
                sections.append(_make_section(document, heading, body))
            heading = match.group(2).strip()
            body = []
            continue

        if heading is None:
            overview.append(line)
        else:
            body.append(line)

    if heading is not None:
        sections.append(_make_section(document, heading, body))

    overview_body = "\n".join(overview).strip()
    if overview_body:
        sections.insert(0, _Section(heading="Overview", body=overview_body))
    return sections


def _make_section(
    document: SourceDocument,
    heading: str,
    lines: list[str],
) -> _Section:
    body = "\n".join(lines).strip()
    if not body:
        raise DocumentChunkError(
            f"{document.source_path}: section {heading!r} has no content"
        )
    return _Section(heading=heading, body=body)


def _slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = _NON_SLUG_CHARACTER.sub("-", ascii_value.lower()).strip("-")
    return slug or "section"
