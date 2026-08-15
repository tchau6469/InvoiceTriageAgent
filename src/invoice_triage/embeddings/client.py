"""Embedding-provider boundary and local Qwen3 implementation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


QWEN3_EMBEDDING_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
QWEN3_MAX_DIMENSIONS = 1024
AP_RETRIEVAL_INSTRUCTION = (
    "Given an accounts-payable question, retrieve vendor contract or spending "
    "policy passages that provide the relevant rule, price, term, or control."
)


@runtime_checkable
class EmbeddingClient(Protocol):
    """Minimal interface shared by ingestion and later vector retrieval."""

    model_id: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed retrieval documents without a query instruction."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one instructed retrieval query."""

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed instructed retrieval queries in a batch."""


class Qwen3EmbeddingClient:
    """Local Sentence Transformers adapter for Qwen3-Embedding-0.6B."""

    def __init__(
        self,
        *,
        model_id: str = QWEN3_EMBEDDING_MODEL_ID,
        dimensions: int = QWEN3_MAX_DIMENSIONS,
        device: str = "cpu",
        batch_size: int = 8,
    ) -> None:
        if not 32 <= dimensions <= QWEN3_MAX_DIMENSIONS:
            raise ValueError("Qwen3 embedding dimensions must be between 32 and 1024")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        self.model_id = model_id
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._device = device
        self._model: Any | None = None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._get_model().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            truncate_dim=self.dimensions,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return self._validated_vectors(vectors.tolist(), expected=len(texts))

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("query text cannot be empty")
        return self.embed_queries([text])[0]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("query text cannot be empty")
        vectors = self._get_model().encode(
            list(texts),
            prompt=f"Instruct: {AP_RETRIEVAL_INSTRUCTION}\nQuery:",
            batch_size=self.batch_size,
            normalize_embeddings=True,
            truncate_dim=self.dimensions,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return self._validated_vectors(vectors.tolist(), expected=len(texts))

    def _get_model(self) -> Any:
        """Load weights only after source validation reaches embedding work."""

        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Qwen embeddings require: python -m pip install -e '.[embeddings]'"
                ) from exc
            self._model = SentenceTransformer(self.model_id, device=self._device)
        return self._model

    def _validated_vectors(
        self,
        vectors: list[list[float]],
        *,
        expected: int,
    ) -> list[list[float]]:
        if len(vectors) != expected:
            raise ValueError(f"embedding provider returned {len(vectors)} of {expected} vectors")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError(
                f"embedding provider output does not match {self.dimensions} dimensions"
            )
        return vectors


class DeterministicEmbeddingClient:
    """Dependency-free normalized vectors for repeatable pipeline tests only."""

    model_id = "test/deterministic-sha256-v1"

    def __init__(self, dimensions: int = QWEN3_MAX_DIMENSIONS) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(f"document\0{text}") for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"query\0{AP_RETRIEVAL_INSTRUCTION}\0{text}")

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(f"{counter}\0{text}".encode()).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        vector = values[: self.dimensions]
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]
