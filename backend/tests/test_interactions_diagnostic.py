from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from google.genai import errors
from google.genai._gaos.errors.genaierror import GenAiError
from google.genai._gaos.lib import compat_errors
from scripts.diagnose_gemini_interactions import (
    CONFIGURED_TIMEOUT_MS,
    CONFIGURED_TIMEOUT_SECONDS,
    create_configured_client,
    extract_safe_text,
    run_diagnostic,
    sanitize_provider_status,
)


@pytest.fixture
def mock_settings():
    return Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=SecretStr("AIzaSyMockKeyForInteractionsDiagnostic123"),
    )


def test_sanitize_provider_status_allowlist():
    assert sanitize_provider_status("DEADLINE_EXCEEDED") == "DEADLINE_EXCEEDED"
    assert sanitize_provider_status("deadline_exceeded") == "DEADLINE_EXCEEDED"
    assert sanitize_provider_status("UNAVAILABLE") == "UNAVAILABLE"
    assert sanitize_provider_status("Arbitrary internal message with secret") == "None"
    assert sanitize_provider_status("https://malicious.url/api") == "None"
    assert sanitize_provider_status(None) == "None"


def test_create_configured_client_sets_timeout_and_retries():
    client = create_configured_client("AIzaSyMockKeyForInteractionsDiagnostic123")
    try:
        assert hasattr(client, "interactions")
        assert hasattr(client.interactions, "sdk_configuration")
        sdk_config = client.interactions.sdk_configuration
        assert sdk_config.timeout_ms == CONFIGURED_TIMEOUT_MS
        assert sdk_config.retry_config is not None
        assert sdk_config.retry_config.strategy == "none"
        assert sdk_config.retry_config.max_retries == 0
        assert sdk_config.retry_config.retry_connection_errors is False
    finally:
        client.close()


def test_create_configured_client_fails_explicitly_if_interactions_missing():
    fake_client = MagicMock(spec=[])  # no interactions attribute
    with patch("scripts.diagnose_gemini_interactions.genai.Client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="Required retry controls could not be applied"):
            create_configured_client("dummy-key")


def test_extract_safe_text_from_output_text():
    interaction = SimpleNamespace(output_text="Hello world!\n")
    assert extract_safe_text(interaction) == "Hello world!"


def test_extract_safe_text_from_steps_fallback():
    item1 = SimpleNamespace(type="text", text="Hello ")
    item2 = SimpleNamespace(type="text", text="there!")
    step = SimpleNamespace(type="model_output", content=[item1, item2])
    interaction = SimpleNamespace(output_text=None, steps=[step])
    assert extract_safe_text(interaction) == "Hello there!"


def test_extract_safe_text_empty_when_no_text_content():
    step = SimpleNamespace(type="thought", content=[SimpleNamespace(type="text", text="internal thinking")])
    interaction = SimpleNamespace(output_text=None, steps=[step])
    assert extract_safe_text(interaction) == ""


def test_diagnostic_fails_when_settings_loading_fails(capsys):
    with patch("scripts.diagnose_gemini_interactions.get_settings", side_effect=ValueError("SecretEnvLoadError: /path/secret")):
        code = run_diagnostic(settings=None)
        assert code == 1

        captured = capsys.readouterr().out
        assert "Result:             CONFIGURATION_ERROR" in captured
        assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
        assert "SecretEnvLoadError" not in captured


def test_diagnostic_fails_when_key_is_missing(capsys):
    unconfigured_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    mock_factory = MagicMock()
    code = run_diagnostic(settings=unconfigured_settings, client_factory=mock_factory)
    assert code == 1
    mock_factory.assert_not_called()

    captured = capsys.readouterr().out
    assert "Result:             CONFIGURATION_ERROR" in captured
    assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
    assert "AI_API_KEY is not configured" in captured


def test_diagnostic_success_format(mock_settings, capsys):
    mock_client = MagicMock()
    mock_interaction = SimpleNamespace(output_text="Hello\n")
    mock_client.interactions.create.return_value = mock_interaction

    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 0

    mock_factory.assert_called_once_with("AIzaSyMockKeyForInteractionsDiagnostic123")
    mock_client.interactions.create.assert_called_once_with(
        model="gemini-3.5-flash-lite",
        input="Reply with the word Hello.",
        store=False,
        generation_config={"thinking_level": "medium"},
        timeout=CONFIGURED_TIMEOUT_SECONDS,
    )
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Model ID:           gemini-3.5-flash-lite" in captured
    assert "API Method:         client.interactions.create" in captured
    assert "Configured Timeout: 60000 ms" in captured
    assert "Result:             SUCCESS" in captured
    assert "Harmless Reply:     Hello" in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_empty_response_fails(mock_settings, capsys):
    mock_client = MagicMock()
    mock_interaction = SimpleNamespace(output_text="")  # empty string
    mock_client.interactions.create.return_value = mock_interaction

    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    EMPTY_OR_INCOMPLETE_RESPONSE" in captured
    assert "HTTP Status:        200" in captured
    assert "Provider Status:    None" in captured


def test_diagnostic_sanitized_compat_internal_server_error(mock_settings, capsys):
    mock_client = MagicMock()
    resp = httpx.Response(
        504,
        request=httpx.Request("POST", "https://example.com"),
        json={"error": {"code": "DEADLINE_EXCEEDED", "message": "Secret internal backend trace"}},
    )
    err = compat_errors.InternalServerError(
        "Secret internal backend trace",
        response=resp,
        body={"error": {"code": "DEADLINE_EXCEEDED", "message": "Secret internal backend trace"}},
    )
    mock_client.interactions.create.side_effect = err
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    InternalServerError" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Secret internal backend trace" not in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_sanitized_compat_timeout_error(mock_settings, capsys):
    mock_client = MagicMock()
    req = httpx.Request("POST", "https://example.com")
    err = compat_errors.APITimeoutError(request=req)
    mock_client.interactions.create.side_effect = err
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    CLIENT_TIMEOUT" in captured
    assert "Exception Class:    APITimeoutError" in captured
    assert "HTTP Status:        None" in captured
    assert "Provider Status:    None" in captured
    assert "before HTTP response" not in captured
    assert "Request timed out" not in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_sanitized_genai_error(mock_settings, capsys):
    mock_client = MagicMock()
    resp = httpx.Response(503, request=httpx.Request("POST", "https://example.com"))
    err = GenAiError("Service unavailable with raw headers", raw_response=resp)
    mock_client.interactions.create.side_effect = err
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    GenAiError" in captured
    assert "HTTP Status:        503" in captured
    assert "Provider Status:    None" in captured
    assert "Service unavailable with raw headers" not in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_sanitized_standard_api_error(mock_settings, capsys):
    mock_client = MagicMock()
    err = errors.ServerError(
        504,
        {"error": {"code": 504, "status": "DEADLINE_EXCEEDED", "message": "Sensitive internal stack trace"}},
    )
    mock_client.interactions.create.side_effect = err
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    ServerError" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Sensitive internal stack trace" not in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_sanitized_generic_exception(mock_settings, capsys):
    mock_client = MagicMock()
    mock_client.interactions.create.side_effect = RuntimeError("Fatal memory corrupt with secret: xyz")
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1
    mock_client.close.assert_called_once()

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    LOCAL_UNEXPECTED_ERROR" in captured
    assert "Exception Class:    RuntimeError" in captured
    assert "HTTP Status:        None" in captured
    assert "Provider Status:    None" in captured
    assert "Fatal memory corrupt with secret: xyz" not in captured
    assert "AIzaSyMockKeyForInteractionsDiagnostic123" not in captured


def test_diagnostic_preserves_original_failure_when_cleanup_also_fails(mock_settings, capsys):
    mock_client = MagicMock()
    resp = httpx.Response(
        504,
        request=httpx.Request("POST", "https://example.com"),
        json={"error": {"code": "DEADLINE_EXCEEDED", "message": "Secret internal backend trace"}},
    )
    err = compat_errors.InternalServerError(
        "Secret internal backend trace",
        response=resp,
        body={"error": {"code": "DEADLINE_EXCEEDED", "message": "Secret internal backend trace"}},
    )
    mock_client.interactions.create.side_effect = err
    mock_client.close.side_effect = RuntimeError("Close socket failure with credential")
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Cleanup Failure:    RuntimeError" in captured
    assert "Close socket failure with credential" not in captured


def test_diagnostic_cleanup_failure_reported_on_success(mock_settings, capsys):
    mock_client = MagicMock()
    mock_interaction = SimpleNamespace(output_text="Hello")
    mock_client.interactions.create.return_value = mock_interaction
    mock_client.close.side_effect = RuntimeError("Close socket failure on success")
    mock_factory = MagicMock(return_value=mock_client)

    code = run_diagnostic(settings=mock_settings, client_factory=mock_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             SUCCESS" in captured
    assert "Cleanup Failure:    RuntimeError" in captured
    assert "Close socket failure on success" not in captured
