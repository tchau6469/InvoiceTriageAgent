"""Model-independent reranker boundary and lazy CrossEncoder adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


QWEN3_RERANKER_MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
MINILM_RERANKER_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
AP_RERANK_INSTRUCTION = (
    "Given an accounts-payable question, determine whether the contract or "
    "spending-policy passage contains the rule, price, term, or control needed "
    "to answer it."
)


@runtime_checkable
class RerankerClient(Protocol):
    """Score query-passage pairs without owning retrieval-stage policy."""

    model_id: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Return one relevance score for every passage, in input order."""


class CrossEncoderRerankerClient:
    """Lazy Sentence Transformers adapter shared by Qwen and MiniLM."""

    def __init__(
        self,
        model_id: str,
        *,
        device: str = "cpu",
        batch_size: int = 4,
        max_length: int = 512,
        instruction: str | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("reranker model_id cannot be empty")
        if batch_size < 1:
            raise ValueError("reranker batch_size must be positive")
        if max_length < 1:
            raise ValueError("reranker max_length must be positive")
        self.model_id = model_id
        self.batch_size = batch_size
        self.max_length = max_length
        self._device = device
        self._instruction = instruction
        self._model: Any | None = None

    @classmethod
    def for_model(
        cls,
        model_id: str,
        *,
        device: str = "cpu",
        batch_size: int = 4,
        max_length: int = 512,
    ) -> CrossEncoderRerankerClient:
        """Apply the AP instruction only to instruction-aware Qwen rerankers."""

        instruction = (
            AP_RERANK_INSTRUCTION
            if model_id.startswith("Qwen/Qwen3-Reranker-")
            else None
        )
        return cls(
            model_id,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
            instruction=instruction,
        )

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not query.strip():
            raise ValueError("reranker query cannot be empty")
        if not passages:
            return []
        if any(not passage.strip() for passage in passages):
            raise ValueError("reranker passages cannot be empty")

        raw_scores = self._get_model().predict(
            [(query, passage) for passage in passages],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        values = raw_scores.tolist() if hasattr(raw_scores, "tolist") else raw_scores
        scores = [float(value) for value in values]
        if len(scores) != len(passages):
            raise ValueError(
                f"reranker returned {len(scores)} scores for {len(passages)} passages"
            )
        return scores

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "Reranking requires: python -m pip install -e '.[embeddings]'"
                ) from exc

            kwargs: dict[str, Any] = {
                "device": self._device,
                "max_length": self.max_length,
            }
            if self._instruction is not None:
                kwargs.update(
                    prompts={"accounts_payable": self._instruction},
                    default_prompt_name="accounts_payable",
                )
            self._model = CrossEncoder(self.model_id, **kwargs)
        return self._model
