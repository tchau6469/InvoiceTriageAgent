"""Tests for the dependency-free embedding contract."""

import math
import sys
from types import SimpleNamespace

import pytest

from invoice_triage.embeddings import (
    AP_RETRIEVAL_INSTRUCTION,
    DeterministicEmbeddingClient,
    Qwen3EmbeddingClient,
)


def test_deterministic_embeddings_are_normalized_and_repeatable() -> None:
    client = DeterministicEmbeddingClient(dimensions=32)

    first = client.embed_documents(["contract price"])[0]
    second = client.embed_documents(["contract price"])[0]

    assert first == second
    assert len(first) == 32
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_query_and_document_embedding_paths_are_distinct() -> None:
    client = DeterministicEmbeddingClient(dimensions=32)

    assert client.embed_query("payment terms") != client.embed_documents(["payment terms"])[0]


def test_qwen_adapter_instructs_queries_but_not_documents(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeVectors:
        def __init__(self, count: int) -> None:
            self._vectors = [[0.5] * 32 for _ in range(count)]

        def tolist(self) -> list[list[float]]:
            return self._vectors

    class FakeSentenceTransformer:
        def __init__(self, model_id: str, *, device: str) -> None:
            assert model_id == "Qwen/Qwen3-Embedding-0.6B"
            assert device == "cpu"

        def encode(self, texts: list[str], **kwargs: object) -> FakeVectors:
            calls.append((texts, kwargs))
            return FakeVectors(len(texts))

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    client = Qwen3EmbeddingClient(dimensions=32)

    assert len(client.embed_documents(["a contract clause"])) == 1
    assert len(client.embed_query("What are the payment terms?")) == 32
    assert "prompt" not in calls[0][1]
    assert calls[1][1]["prompt"] == f"Instruct: {AP_RETRIEVAL_INSTRUCTION}\nQuery:"
    assert calls[0][1]["normalize_embeddings"] is True
    assert calls[1][1]["normalize_embeddings"] is True
