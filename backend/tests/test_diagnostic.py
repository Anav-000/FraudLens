from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from scripts.diagnose_raw_gemini import create_client, create_content_config, run_diagnostic
from google.genai import errors


@pytest.fixture
def mock_settings():
    return Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=SecretStr("AIzaSyMockKeyForDiagnosticTest12345"),
    )


def test_create_client_configures_strict_timeout_and_retries():
    with patch("scripts.diagnose_raw_gemini.genai.Client") as mock_genai_client_cls:
        create_client("mock-key-123")
        mock_genai_client_cls.assert_called_once()
        _, kwargs = mock_genai_client_cls.call_args
        assert kwargs["api_key"] == "mock-key-123"
        assert kwargs["http_options"].timeout == 60_000
        assert kwargs["http_options"].retry_options.attempts == 1


def test_create_content_config_omits_schema_and_sets_store_false():
    config = create_content_config()
    assert config.store is False
    assert config.tools is None
    assert getattr(config, "response_schema", None) is None
    assert getattr(config, "response_mime_type", None) is None


@pytest.mark.asyncio
async def test_diagnostic_fails_when_settings_loading_fails(capsys):
    with patch("scripts.diagnose_raw_gemini.get_settings", side_effect=ValueError("SecretEnvLoadError: /path/secret")):
        code = await run_diagnostic(settings=None)
        assert code == 1

        captured = capsys.readouterr().out
        assert "Result:             CONFIGURATION_ERROR" in captured
        assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
        assert "SecretEnvLoadError" not in captured


@pytest.mark.asyncio
async def test_diagnostic_fails_when_key_is_missing(capsys):
    unconfigured_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )

    mock_factory = MagicMock()
    code = await run_diagnostic(settings=unconfigured_settings, client_factory=mock_factory)
    assert code == 1
    mock_factory.assert_not_called()

    captured = capsys.readouterr().out
    assert "Result:             CONFIGURATION_ERROR" in captured
    assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
    assert "AI_API_KEY is not configured" in captured


@pytest.mark.asyncio
async def test_diagnostic_direct_success_format(mock_settings, capsys):
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello\n"

    mock_generate = AsyncMock(return_value=mock_response)
    mock_aclose = AsyncMock()

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 0

    mock_factory.assert_called_once_with("AIzaSyMockKeyForDiagnosticTest12345")
    mock_generate.assert_awaited_once()
    mock_aclose.assert_awaited_once()

    captured = capsys.readouterr().out
    assert "Result:             SUCCESS" in captured
    assert "Model ID:           gemini-3.5-flash-lite" in captured
    assert "Configured Timeout: 60000 ms" in captured
    assert "Harmless Reply:     Hello" in captured
    assert "AIzaSyMockKeyForDiagnosticTest12345" not in captured


@pytest.mark.asyncio
async def test_diagnostic_empty_response_fails(mock_settings, capsys):
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "   "  # whitespace only

    mock_generate = AsyncMock(return_value=mock_response)
    mock_aclose = AsyncMock()

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    EMPTY_OR_INCOMPLETE_RESPONSE" in captured
    assert "HTTP Status:        200" in captured
    assert "Provider Status:    None" in captured


@pytest.mark.asyncio
async def test_diagnostic_sanitized_504_failure_format(mock_settings, capsys):
    mock_genai_client = MagicMock()
    err_504 = errors.ServerError(
        504,
        {"error": {"code": 504, "message": "Deadline exceeded waiting for model", "status": "DEADLINE_EXCEEDED"}},
    )
    mock_generate = AsyncMock(side_effect=err_504)
    mock_aclose = AsyncMock()

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    mock_aclose.assert_awaited_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    ServerError" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Deadline exceeded waiting for model" not in captured
    assert "AIzaSyMockKeyForDiagnosticTest12345" not in captured


@pytest.mark.asyncio
async def test_diagnostic_sanitized_503_failure_format(mock_settings, capsys):
    mock_genai_client = MagicMock()
    err_503 = errors.ServerError(
        503,
        {"error": {"code": 503, "message": "The service is temporarily unavailable", "status": "UNAVAILABLE"}},
    )
    mock_generate = AsyncMock(side_effect=err_503)
    mock_aclose = AsyncMock()

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    mock_aclose.assert_awaited_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    ServerError" in captured
    assert "HTTP Status:        503" in captured
    assert "Provider Status:    UNAVAILABLE" in captured


@pytest.mark.asyncio
async def test_diagnostic_sanitized_client_timeout_format(mock_settings, capsys):
    mock_genai_client = MagicMock()
    mock_generate = AsyncMock(side_effect=httpx.ReadTimeout("Client timed out after 60s"))
    mock_aclose = AsyncMock()

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    mock_aclose.assert_awaited_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    CLIENT_TIMEOUT" in captured
    assert "Exception Class:    ReadTimeout" in captured
    assert "HTTP Status:        None" in captured
    assert "Provider Status:    None" in captured
    assert "before HTTP response" not in captured
    assert "Client timed out after 60s" not in captured
    assert "AIzaSyMockKeyForDiagnosticTest12345" not in captured


@pytest.mark.asyncio
async def test_diagnostic_preserves_original_failure_when_cleanup_also_fails(mock_settings, capsys):
    mock_genai_client = MagicMock()
    err_504 = errors.ServerError(
        504,
        {"error": {"code": 504, "message": "Deadline exceeded", "status": "DEADLINE_EXCEEDED"}},
    )
    mock_generate = AsyncMock(side_effect=err_504)
    mock_aclose = AsyncMock(side_effect=RuntimeError("Aclose transport reset failure"))

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Cleanup Failure:    RuntimeError" in captured
    assert "Aclose transport reset failure" not in captured


@pytest.mark.asyncio
async def test_diagnostic_cleanup_failure_reported_on_success(mock_settings, capsys):
    mock_genai_client = MagicMock()
    mock_response = MagicMock(text="Hello")
    mock_generate = AsyncMock(return_value=mock_response)
    mock_aclose = AsyncMock(side_effect=RuntimeError("Cleanup close socket error"))

    mock_genai_client.aio.models.generate_content = mock_generate
    mock_genai_client.aio.aclose = mock_aclose

    mock_factory = MagicMock(return_value=mock_genai_client)

    code = await run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             SUCCESS" in captured
    assert "Cleanup Failure:    RuntimeError" in captured
    assert "Cleanup close socket error" not in captured
