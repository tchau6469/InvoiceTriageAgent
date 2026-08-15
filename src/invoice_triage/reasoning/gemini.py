"""Gemini implementation of provider-neutral structured reasoning."""

from __future__ import annotations

from typing import Any

from invoice_triage.reasoning.base import (
    ReasoningTokenUsage,
    StructuredGeneration,
    StructuredResponse,
)


class GeminiReasoningError(RuntimeError):
    """Gemini did not return a response that satisfies the requested schema."""


class GeminiReasoningClient:
    """Call Gemini asynchronously and validate every structured response locally.

    The Google SDK import is intentionally lazy. Unit tests can inject a small
    async client, while the production container installs the optional SDK.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str = "gemini-3.5-flash",
        async_client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key cannot be empty")
        if not model_id.strip():
            raise ValueError("Gemini model ID cannot be empty")
        self._api_key = api_key
        self._model_id = model_id
        self._async_client = async_client

    @property
    def model_id(self) -> str:
        return self._model_id

    async def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_model: type[StructuredResponse],
    ) -> StructuredGeneration[StructuredResponse]:
        config = {
            "system_instruction": system_instruction,
            "response_mime_type": "application/json",
            # The SDK's OpenAPI-style ``response_schema`` converter rejects
            # Pydantic's ``additionalProperties: false``. Gemini's native JSON
            # Schema field supports it and preserves our strict contract.
            "response_json_schema": response_model.model_json_schema(),
            # This call never gives Gemini executable Python tools. Disabling
            # SDK-side AFC avoids a noisy warning on the MCP stdio transport.
            "automatic_function_calling": {"disable": True},
        }
        if self._async_client is not None:
            response = await self._async_client.models.generate_content(
                model=self._model_id,
                contents=prompt,
                config=config,
            )
        else:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover - deployment guard
                raise GeminiReasoningError(
                    "google-genai is required for Gemini reasoning"
                ) from exc

            async with genai.Client(api_key=self._api_key).aio as client:
                response = await client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=config,
                )

        parsed = getattr(response, "parsed", None)
        try:
            if isinstance(parsed, response_model):
                value = parsed
            elif parsed is not None:
                value = response_model.model_validate(parsed)
            else:
                text = getattr(response, "text", None)
                if not text:
                    raise GeminiReasoningError(
                        "Gemini returned neither parsed data nor response text"
                    )
                value = response_model.model_validate_json(text)
        except GeminiReasoningError:
            raise
        except Exception as exc:
            raise GeminiReasoningError(
                "Gemini structured response failed local schema validation"
            ) from exc

        usage_metadata = getattr(response, "usage_metadata", None)
        usage = ReasoningTokenUsage(
            input_tokens=_optional_int(usage_metadata, "prompt_token_count"),
            output_tokens=_optional_int(usage_metadata, "candidates_token_count"),
            total_tokens=_optional_int(usage_metadata, "total_token_count"),
        )
        return StructuredGeneration(value=value, model_id=self._model_id, usage=usage)


def _optional_int(value: object, attribute: str) -> int | None:
    candidate = getattr(value, attribute, None)
    return candidate if isinstance(candidate, int) else None
