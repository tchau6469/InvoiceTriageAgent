"""Application settings loaded from explicit environment variables."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Environment(StrEnum):
    """Supported application environments."""

    DEVELOPMENT = "dev"
    TEST = "test"
    PRODUCTION = "prod"


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
        }
        values = {
            field: os.environ[f"{prefix}{suffix}"]
            for field, suffix in names.items()
            if f"{prefix}{suffix}" in os.environ
        }
        return cls.model_validate(values)
