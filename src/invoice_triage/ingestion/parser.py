"""Strict Markdown and YAML-front-matter parsing for grounding documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from invoice_triage.domain import SourceDocument


class DocumentParseError(ValueError):
    """A source file cannot be converted into the document domain contract."""


_FRONT_MATTER_DELIMITER = "---"
_H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_ALLOWED_FRONT_MATTER = {
    "document_id",
    "document_type",
    "vendor_id",
    "category",
    "effective_date",
    "expiration_date",
    "status",
    "metadata",
}


def parse_markdown_document(
    path: Path,
    *,
    source_root: Path | None = None,
) -> SourceDocument:
    """Parse one UTF-8 Markdown source with strict YAML front matter."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DocumentParseError(f"cannot read Markdown source {path}: {exc}") from exc

    front_matter, body = _split_front_matter(raw, path)
    title = _extract_title(body, path)
    source_path = _portable_source_path(path, source_root)

    unknown = set(front_matter) - _ALLOWED_FRONT_MATTER
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise DocumentParseError(f"{source_path}: unknown front-matter fields: {fields}")

    metadata = front_matter.pop("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise DocumentParseError(f"{source_path}: metadata must be a YAML mapping")

    try:
        return SourceDocument.model_validate(
            {
                **front_matter,
                "title": title,
                "content": body.strip(),
                "source_path": source_path,
                "metadata": {**metadata, "source_format": "markdown"},
            }
        )
    except ValueError as exc:
        raise DocumentParseError(f"{source_path}: invalid document metadata: {exc}") from exc


def _split_front_matter(raw: str, path: Path) -> tuple[dict[str, Any], str]:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise DocumentParseError(f"{path}: Markdown source must begin with YAML front matter")

    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == _FRONT_MATTER_DELIMITER
        )
    except StopIteration as exc:
        raise DocumentParseError(f"{path}: YAML front matter is not closed") from exc

    yaml_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        raise DocumentParseError(f"{path}: Markdown body is empty")

    try:
        value = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise DocumentParseError(f"{path}: invalid YAML front matter: {exc}") from exc
    if not isinstance(value, dict):
        raise DocumentParseError(f"{path}: YAML front matter must be a mapping")
    return dict(value), body


def _extract_title(body: str, path: Path) -> str:
    headings = _H1_PATTERN.findall(body)
    if len(headings) != 1:
        raise DocumentParseError(
            f"{path}: Markdown body must contain exactly one level-one title"
        )
    return headings[0].strip()


def _portable_source_path(path: Path, source_root: Path | None) -> str:
    resolved = path.resolve()
    if source_root is None:
        return path.as_posix()
    try:
        return resolved.relative_to(source_root.resolve()).as_posix()
    except ValueError as exc:
        raise DocumentParseError(f"{path}: source is outside {source_root}") from exc
