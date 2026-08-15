"""Application settings loaded from explicit environment variables."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Environment(StrEnum):
    """Supported application environments."""

    DEVELOPMENT = "dev"
    TEST = "test"
    PRODUCTION = "prod"


class ReasoningProvider(StrEnum):
    """Hosted structured-reasoning implementations currently available."""

    GEMINI = "gemini"


class AppSettings(BaseModel):
    """Runtime configuration shared across local and deployed environments.

    The project intentionally avoids implicit `.env` loading. Local shells or a
    future process runner may load that file, while deployed environments can
    inject the same variables through their secrets and configuration systems.
    """

    model_config = ConfigDict(extra="forbid")

    environment: Environment = Environment.DEVELOPMENT
    database_url: SecretStr = SecretStr(
        "postgresql://invoice_triage:invoice_triage@localhost:5432/invoice_triage"
    )
    embedding_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimensions: int = Field(default=1024, gt=0)
    embedding_device: str = "cpu"
    embedding_batch_size: int = Field(default=8, ge=1, le=256)
    retrieval_top_k: int = Field(default=5, ge=1, le=100)
    vector_candidates: int = Field(default=20, ge=1, le=1000)
    keyword_candidates: int = Field(default=20, ge=1, le=1000)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_candidates: int = Field(default=10, ge=1, le=100)
    reranker_model_id: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_device: str = "cpu"
    reranker_batch_size: int = Field(default=4, ge=1, le=256)
    reranker_max_length: int = Field(default=512, ge=32, le=32768)
    reasoning_provider: ReasoningProvider = ReasoningProvider.GEMINI
    reasoning_model_id: str = "gemini-3.5-flash"
    gemini_api_key: SecretStr | None = None
    invoice_source_root: Path = Path("fixtures/invoices")

    @classmethod
    def from_environment(cls) -> Self:
        """Build settings from the project's namespaced environment variables."""

        prefix = "INVOICE_TRIAGE_"
        names = {
            "environment": "ENVIRONMENT",
            "database_url": "DATABASE_URL",
            "embedding_model_id": "EMBEDDING_MODEL_ID",
            "embedding_dimensions": "EMBEDDING_DIMENSIONS",
            "embedding_device": "EMBEDDING_DEVICE",
            "embedding_batch_size": "EMBEDDING_BATCH_SIZE",
            "retrieval_top_k": "RETRIEVAL_TOP_K",
            "vector_candidates": "VECTOR_CANDIDATES",
            "keyword_candidates": "KEYWORD_CANDIDATES",
            "rrf_k": "RRF_K",
            "rerank_candidates": "RERANK_CANDIDATES",
            "reranker_model_id": "RERANKER_MODEL_ID",
            "reranker_device": "RERANKER_DEVICE",
            "reranker_batch_size": "RERANKER_BATCH_SIZE",
            "reranker_max_length": "RERANKER_MAX_LENGTH",
            "reasoning_provider": "REASONING_PROVIDER",
            "reasoning_model_id": "REASONING_MODEL_ID",
            "invoice_source_root": "INVOICE_SOURCE_ROOT",
        }
        values = {
            field: os.environ[f"{prefix}{suffix}"]
            for field, suffix in names.items()
            if f"{prefix}{suffix}" in os.environ
        }
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        if api_key is not None:
            values["gemini_api_key"] = api_key
        return cls.model_validate(values)
