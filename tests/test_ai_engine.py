"""Unit tests for the AI engine (multi-provider).

The Gemini API is mocked; no paid API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_engine import AIEngine, GenerationResult


@pytest.fixture
def engine() -> AIEngine:
    e = AIEngine(provider="gemini", api_key="test-key")
    # Force availability for generate-path tests without hitting the network.
    e._available = True
    return e


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    e = AIEngine(provider="gemini")
    assert e.available is False
    assert e.init_error() is not None
    assert "GEMINI_API_KEY" in e.init_error()


def test_generate_returns_structured_output(engine: AIEngine) -> None:
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.output_text = (
        '{"clarification_needed": false, '
        '"clarification_question": null, '
        '"sql": "SELECT COUNT(*) FROM customers", '
        '"explanation": "Counts all customers."}'
    )
    mock_model.interactions.create.return_value = mock_response
    engine._client = mock_model

    result = engine.generate("How many customers?", {})

    assert result.error is None
    assert result.sql == "SELECT COUNT(*) FROM customers"
    assert result.clarification_needed is False
    assert result.explanation == "Counts all customers."
    assert result.raw is not None
    assert result.provider == "gemini"
    mock_model.interactions.create.assert_called_once()
    assert mock_model.interactions.create.call_args.kwargs["store"] is False
    assert (
        mock_model.interactions.create.call_args.kwargs["response_format"][
            "mime_type"
        ]
        == "application/json"
    )


def test_generate_clarification_needed(engine: AIEngine) -> None:
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.output_text = (
        '{"clarification_needed": true, '
        '"clarification_question": "Do you mean highest spending or most orders?", '
        '"sql": null, '
        '"explanation": null}'
    )
    mock_model.interactions.create.return_value = mock_response
    engine._client = mock_model

    result = engine.generate("Show me the best customers.", {})

    assert result.error is None
    assert result.clarification_needed is True
    assert result.sql is None
    assert "highest spending" in result.clarification_question


def test_generate_non_json_handled_gracefully(engine: AIEngine) -> None:
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.output_text = "This is definitely not JSON."
    mock_model.interactions.create.return_value = mock_response
    engine._client = mock_model

    result = engine.generate("anything", {})

    assert result.sql is None
    assert result.error is not None


def test_generate_provider_error(engine: AIEngine) -> None:
    mock_model = MagicMock()
    mock_model.interactions.create.side_effect = RuntimeError("API down")
    engine._client = mock_model

    result = engine.generate("anything", {})

    assert result.sql is None
    assert result.error is not None
    assert "Gemini request failed (RuntimeError)" in result.error


def test_gemini_not_found_error_is_actionable_and_does_not_expose_key(
    engine: AIEngine,
) -> None:
    class NotFoundError(Exception):
        code = 404

    engine.model_name = "retired-model"
    engine._client = MagicMock()
    engine._client.interactions.create.side_effect = NotFoundError(
        "provider response containing a secret"
    )

    result = engine.generate("anything", {})

    assert result.error is not None
    assert "retired-model" in result.error
    assert "GEMINI_MODEL" in result.error
    assert "test-key" not in result.error
    assert "provider response containing a secret" not in result.error


def test_gemini_model_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    e = AIEngine(provider="gemini", api_key="test-key")

    assert e.model_name == "gemini-3.5-flash"


def test_unavailable_engine_returns_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    e = AIEngine(provider="gemini")
    assert e.available is False
    result = e.generate("anything", {})
    assert result.sql is None
    assert result.error is not None


def test_openrouter_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    e = AIEngine(provider="openrouter")
    assert e.available is False
    assert e.init_error() is not None
    assert "OPENROUTER_API_KEY" in e.init_error()


def test_ollama_engine_init(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ollama doesn't require an API key; just checks import of requests.
    e = AIEngine(provider="ollama")
    assert e.available is True
    assert e.provider == "ollama"


def test_unknown_provider() -> None:
    e = AIEngine(provider="nonexistent")
    assert e.available is False
    assert e.init_error() is not None
    assert "Unknown AI provider" in e.init_error()


def test_openai_compatible_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    e = AIEngine(provider="openai")
    assert e.available is False
    assert e.init_error() is not None


def test_openai_compatible_missing_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
    e = AIEngine(provider="openai")
    assert e.available is False
    assert e.init_error() is not None
    assert "OPENAI_COMPATIBLE_BASE_URL" in e.init_error()


def test_openai_compatible_engine_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "nemotron-3.5-super-vl-free")
    e = AIEngine(provider="openai")
    assert e.available is True
    assert e.provider == "openai"
    assert e.model_name == "nemotron-3.5-super-vl-free"


def test_opencode_model_in_list() -> None:
    from ai_engine import OPENCODE_FREE_MODELS
    assert "nemotron-3.5-super-vl-free" in OPENCODE_FREE_MODELS
