"""Tests for explicit, namespaced runtime configuration."""

import pytest
from pydantic import ValidationError

from invoice_triage.config import AppSettings, Environment, ReasoningProvider


def test_settings_have_safe_local_defaults() -> None:
    settings = AppSettings()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.retrieval_top_k == 5
    assert settings.rerank_candidates == 10
    assert settings.reranker_model_id == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert settings.database_url.get_secret_value().startswith("postgresql://")
    assert "database_url=" not in repr(settings.database_url)
    assert settings.reasoning_provider is ReasoningProvider.GEMINI
    assert settings.reasoning_model_id == "gemini-3.5-flash"
    assert settings.gemini_api_key is None


def test_settings_load_namespaced_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICE_TRIAGE_ENVIRONMENT", "test")
    monkeypatch.setenv("INVOICE_TRIAGE_RETRIEVAL_TOP_K", "8")
    monkeypatch.setenv("INVOICE_TRIAGE_EMBEDDING_DIMENSIONS", "1536")

    settings = AppSettings.from_environment()

    assert settings.environment is Environment.TEST
    assert settings.retrieval_top_k == 8
    assert settings.embedding_dimensions == 1536


def test_settings_load_gemini_key_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-secret")
    monkeypatch.setenv("INVOICE_TRIAGE_REASONING_MODEL_ID", "gemini-test")

    settings = AppSettings.from_environment()

    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "synthetic-test-secret"
    assert "synthetic-test-secret" not in repr(settings)
    assert settings.reasoning_model_id == "gemini-test"


def test_settings_reject_invalid_candidate_count() -> None:
    with pytest.raises(ValidationError):
        AppSettings(vector_candidates=0)
