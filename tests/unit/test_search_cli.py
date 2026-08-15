"""Tests for the single-query retrieval CLI contract."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from invoice_triage.cli import search as search_cli
from invoice_triage.config import AppSettings
from invoice_triage.domain import (
    DocumentChunk,
    DocumentType,
    RetrievalQuery,
    SearchResult,
    VendorCategory,
)
from invoice_triage.retrieval import RetrievalMode


def test_parser_defaults_to_vector_and_accepts_filters() -> None:
    args = search_cli.build_parser().parse_args(
        [
            "Explain CSP-05",
            "--top-k",
            "3",
            "--category",
            "cloud_software",
            "--vendor-id",
            "VND-1001",
            "--as-of-date",
            "2026-07-01",
            "--metadata-filter",
            '{"clause_id":"CSP-05"}',
        ]
    )

    assert args.mode == "vector"
    assert args.top_k == 3
    assert args.category == "cloud_software"
    assert args.vendor_id == "VND-1001"
    assert args.as_of_date.isoformat() == "2026-07-01"
    assert args.metadata_filter == {"clause_id": "CSP-05"}


@pytest.mark.parametrize("value", ["0", "101", "not-a-number"])
def test_parser_rejects_invalid_top_k(value: str) -> None:
    with pytest.raises(SystemExit):
        search_cli.build_parser().parse_args(["query", "--top-k", value])


def test_default_search_does_not_initialize_reranker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _install_fakes(monkeypatch)

    assert search_cli.main(["payment terms", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls.mode is RetrievalMode.VECTOR
    assert calls.request.top_k == 5
    assert calls.reranker_model_id is None
    assert payload["mode"] == "vector"
    assert payload["results"][0]["chunk"]["document_id"] == "POL-CLI"


def test_hybrid_reranked_initializes_selected_model_and_preserves_filters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _install_fakes(monkeypatch)

    assert (
        search_cli.main(
            [
                "CSP-05",
                "--mode",
                "hybrid_reranked",
                "--reranker-model-id",
                "test/reranker",
                "--category",
                "cloud_software",
                "--as-of-date",
                "2025-09-30",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert calls.mode is RetrievalMode.HYBRID_RERANKED
    assert calls.reranker_model_id == "test/reranker"
    assert calls.request.category is VendorCategory.CLOUD_SOFTWARE
    assert calls.request.as_of_date.isoformat() == "2025-09-30"
    assert "Mode: hybrid_reranked" in output
    assert "Cloud Software Policy — CSP-05" in output
    assert "rrf=0.900000" in output
    assert "reranker=0.950000" in output


def test_reranker_override_requires_reranked_mode() -> None:
    with pytest.raises(SystemExit) as error:
        search_cli.main(["query", "--reranker-model-id", "test/reranker"])

    assert error.value.code == 2


class Calls:
    mode: RetrievalMode | None = None
    request: RetrievalQuery | None = None
    reranker_model_id: str | None = None


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> Calls:
    settings = AppSettings(database_url="postgresql://test:test@postgres/test")
    calls = Calls()
    database = _FakeDatabase()

    monkeypatch.setattr(
        search_cli.AppSettings,
        "from_environment",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setattr(
        search_cli,
        "Qwen3EmbeddingClient",
        lambda **kwargs: SimpleNamespace(model_id=kwargs["model_id"]),
    )
    monkeypatch.setattr(
        search_cli.Database,
        "from_settings",
        classmethod(lambda cls, supplied_settings: database),
    )

    class FakeRerankerFactory:
        @classmethod
        def for_model(cls, model_id: str, **kwargs: object) -> object:
            calls.reranker_model_id = model_id
            return SimpleNamespace(model_id=model_id)

    class FakeService:
        @classmethod
        def from_settings(
            cls,
            supplied_database: object,
            embedding_client: object,
            supplied_settings: AppSettings,
            *,
            reranker_client: object | None = None,
        ) -> FakeService:
            assert supplied_database is database
            assert embedding_client is not None
            assert supplied_settings is settings
            if reranker_client is None:
                assert calls.reranker_model_id is None
            return cls()

        def search(
            self,
            request: RetrievalQuery,
            *,
            mode: RetrievalMode,
        ) -> tuple[SearchResult, ...]:
            calls.request = request
            calls.mode = mode
            return (_result(),)

    monkeypatch.setattr(search_cli, "CrossEncoderRerankerClient", FakeRerankerFactory)
    monkeypatch.setattr(search_cli, "RetrievalService", FakeService)
    return calls


class _FakeDatabase:
    def __enter__(self) -> _FakeDatabase:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _result() -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id="POL-CLI:csp-05",
            document_id="POL-CLI",
            document_type=DocumentType.SPENDING_POLICY,
            section="CSP-05",
            ordinal=0,
            content="Account-management fees are not payable.",
            source_path="fixtures/policies/cloud-software.md",
            category=VendorCategory.CLOUD_SOFTWARE,
            metadata={"document_title": "Cloud Software Policy"},
        ),
        rank=1,
        combined_score=0.9,
        vector_score=0.9,
        reranker_score=0.95,
    )
