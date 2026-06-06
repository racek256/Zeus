"""LLM client for AthenaAI model-backed control decisions.

The client uses the OpenAI Python package against an OpenAI-compatible base URL.
It keeps API keys out of logs and returns only provider-visible response text,
never hidden chain-of-thought.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Protocol

from athenaai.config import get_opencode_api_key, get_opencode_api_url


class ModelClientError(RuntimeError):
    """Raised when the model client cannot obtain usable response text."""


class ModelActionClient(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        timeout_s: float = 60.0,
    ) -> str:
        """Return a JSON response string from a model."""
        ...


@dataclass(frozen=True)
class OpenCodeModelClient:
    api_key: str | None = None
    api_url: str | None = None

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        timeout_s: float = 60.0,
    ) -> str:
        api_key = self.api_key if self.api_key is not None else get_opencode_api_key()
        if not api_key:
            raise ModelClientError("OPENCODE_GO_API_KEY is not configured")

        api_url = self.api_url if self.api_url is not None else get_opencode_api_url()
        try:
            openai_module = importlib.import_module("openai")
        except ImportError as exc:
            raise ModelClientError("openai Python package is required for model control") from exc

        try:
            client = openai_module.OpenAI(
                api_key=api_key,
                base_url=api_url,
                timeout=timeout_s,
            )
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            choices: Any = getattr(completion, "choices", None)
            if not isinstance(choices, list) or not choices:
                raise ModelClientError("Model API response did not include choices")
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if not isinstance(content, str) or not content.strip():
                raise ModelClientError("Model API message content was empty")
            return content
        except ModelClientError:
            raise
        except Exception as exc:
            raise ModelClientError(f"Model API call failed: {type(exc).__name__}: {str(exc)[:500]}") from exc
