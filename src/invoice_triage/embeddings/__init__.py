"""Embedding-provider abstractions."""

from invoice_triage.embeddings.client import (
    AP_RETRIEVAL_INSTRUCTION,
    QWEN3_EMBEDDING_MODEL_ID,
    DeterministicEmbeddingClient,
    EmbeddingClient,
    Qwen3EmbeddingClient,
)

__all__ = [
    "AP_RETRIEVAL_INSTRUCTION",
    "QWEN3_EMBEDDING_MODEL_ID",
    "DeterministicEmbeddingClient",
    "EmbeddingClient",
    "Qwen3EmbeddingClient",
]
