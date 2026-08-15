"""Provider-neutral contracts for validated structured model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ReasoningTokenUsage:
    """Token counts reported by a reasoning provider when available."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class StructuredGeneration(Generic[StructuredResponse]):
    """One provider response after local schema validation."""

    value: StructuredResponse
    model_id: str
    usage: ReasoningTokenUsage


class StructuredReasoningClient(Protocol):
    """Small interface that keeps business logic independent of Gemini."""

    async def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_model: type[StructuredResponse],
    ) -> StructuredGeneration[StructuredResponse]:
        """Generate and validate one response against ``response_model``."""

