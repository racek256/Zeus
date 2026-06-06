"""Tests for OpenCode/OpenAI-compatible model client."""

from __future__ import annotations

from unittest.mock import patch
import unittest

from athenaai.model_client import ModelClientError, OpenCodeModelClient


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content: str | None = '{"reasoning":"ok","action":null}', choices=True) -> None:
        self.choices = [FakeChoice(content)] if choices else []


class FakeCompletions:
    def __init__(self, completion: FakeCompletion) -> None:
        self._completion = completion
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._completion


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeOpenAIInstance:
    def __init__(self, completions: FakeCompletions, **kwargs) -> None:
        self.kwargs = kwargs
        self.chat = FakeChat(completions)


class FakeOpenAIModule:
    def __init__(self, completion: FakeCompletion) -> None:
        self.completions = FakeCompletions(completion)
        self.instances: list[FakeOpenAIInstance] = []

    def OpenAI(self, **kwargs):
        instance = FakeOpenAIInstance(self.completions, **kwargs)
        self.instances.append(instance)
        return instance


def test_opencode_model_client_returns_message_content() -> None:
    fake_openai = FakeOpenAIModule(FakeCompletion())

    with patch("importlib.import_module", return_value=fake_openai):
        client = OpenCodeModelClient(
            api_key="test-key",
            api_url="https://example.test/v1",
        )
        result = client.complete_json(
            model="deepseek-v4-pro",
            system_prompt="Return JSON only.",
            user_prompt="{}",
            timeout_s=12.0,
        )

    assert result == '{"reasoning":"ok","action":null}'
    assert fake_openai.instances[0].kwargs["api_key"] == "test-key"
    assert fake_openai.instances[0].kwargs["base_url"] == "https://example.test/v1"
    assert fake_openai.instances[0].kwargs["timeout"] == 12.0
    assert fake_openai.completions.calls[0]["model"] == "deepseek-v4-pro"
    assert fake_openai.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_opencode_model_client_requires_api_key() -> None:
    client = OpenCodeModelClient(api_key="", api_url="https://example.test/v1")
    with unittest.TestCase().assertRaisesRegex(ModelClientError, "OPENCODE_GO_API_KEY"):
        client.complete_json(
            model="deepseek-v4-pro",
            system_prompt="Return JSON only.",
            user_prompt="{}",
        )


def test_opencode_model_client_rejects_missing_choices() -> None:
    fake_openai = FakeOpenAIModule(FakeCompletion(choices=False))

    with patch("importlib.import_module", return_value=fake_openai):
        client = OpenCodeModelClient(api_key="test-key", api_url="https://example.test/v1")
        with unittest.TestCase().assertRaisesRegex(ModelClientError, "choices"):
            client.complete_json(
                model="deepseek-v4-pro",
                system_prompt="Return JSON only.",
                user_prompt="{}",
            )
