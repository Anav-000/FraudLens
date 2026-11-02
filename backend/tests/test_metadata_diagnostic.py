from unittest.mock import patch
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from scripts.diagnose_gemini_metadata import (
    DIAGNOSTIC_TIMEOUT_MS,
    create_client,
    run_diagnostic,
    sanitize_provider_status,
)


@pytest.fixture
def mock_settings():
    return Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=SecretStr("AIzaSyMockKeyForMetadataDiagnostic123"),
    )


def test_sanitize_provider_status():
    assert sanitize_provider_status("OK") == "OK"
    assert sanitize_provider_status("NOT_FOUND") == "NOT_FOUND"
    assert sanitize_provider_status("deadline_exceeded") == "DEADLINE_EXCEEDED"
    assert sanitize_provider_status("arbitrary string") == "None"
    assert sanitize_provider_status(None) == "None"


def test_create_client_configures_timeout_and_retries():
    client = create_client("mock-key-123")
    try:
        assert client._api_client._http_options.timeout == DIAGNOSTIC_TIMEOUT_MS
        assert client._api_client._http_options.retry_options.attempts == 1
    finally:
        client.close()


@pytest.mark.asyncio
async def test_metadata_diagnostic_success_with_mock_transport(mock_settings, capsys):
    called_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_requests.append(request)
        assert request.method == "GET"
        assert "generativelanguage.googleapis.com" in str(request.url)
        assert "/v1beta/models/gemini-3.5-flash-lite" in str(request.url)
        return httpx.Response(
            200,
            text='{"name": "models/gemini-3.5-flash-lite", "displayName": "Gemini 3.5 Flash Lite"}',
            request=request,
        )

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 0
    assert len(called_requests) == 1

    captured = capsys.readouterr().out
    assert "Operation:          client.aio.models.get" in captured
    assert "Model ID:           gemini-3.5-flash-lite" in captured
    assert "Configured Timeout: 60000 ms" in captured
    assert "Result:             SUCCESS" in captured
    assert "Provider Status:    OK" in captured
    assert "Cleanup Status:     Clean" in captured
    assert "HTTP Status:        200" not in captured  # does not invent 200 on success
    assert "AIzaSyMockKeyForMetadataDiagnostic123" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_404_with_mock_transport(mock_settings, capsys):
    called_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_requests.append(request)
        return httpx.Response(
            404,
            text='{"error": {"code": 404, "message": "models/gemini-3.5-flash-lite is not found for API version v1beta", "status": "NOT_FOUND"}}',
            request=request,
        )

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 1
    assert len(called_requests) == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    ClientError" in captured
    assert "HTTP Status:        404" in captured
    assert "Provider Status:    NOT_FOUND" in captured
    assert "Cleanup Status:     Clean" in captured
    assert "is not found for API version" not in captured
    assert "AIzaSyMockKeyForMetadataDiagnostic123" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_timeout_with_mock_transport(mock_settings, capsys):
    called_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_requests.append(request)
        raise httpx.ReadTimeout("Mocked transport timeout", request=request)

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 1
    assert len(called_requests) == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    CLIENT_TIMEOUT" in captured
    assert "Exception Class:    ReadTimeout" in captured
    assert "HTTP Status:        None" in captured
    assert "Provider Status:    None" in captured
    assert "Cleanup Status:     Clean" in captured
    assert "before HTTP response" not in captured
    assert "Mocked transport timeout" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_503_with_mock_transport(mock_settings, capsys):
    called_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_requests.append(request)
        return httpx.Response(
            503,
            text='{"error": {"code": 503, "status": "UNAVAILABLE", "message": "Service unavailable"}}',
            request=request,
        )

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 1
    assert len(called_requests) == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "Exception Class:    ServerError" in captured
    assert "HTTP Status:        503" in captured
    assert "Provider Status:    UNAVAILABLE" in captured
    assert "Cleanup Status:     Clean" in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_preserves_primary_failure_on_cleanup_failure(mock_settings, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            504,
            text='{"error": {"code": 504, "status": "DEADLINE_EXCEEDED", "message": "Deadline exceeded"}}',
            request=request,
        )

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        # Patch aclose to raise
        c.aio.aclose = patch.object(c.aio, "aclose", side_effect=RuntimeError("Aclose transport reset failure")).start()
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    PROVIDER_HTTP_ERROR" in captured
    assert "HTTP Status:        504" in captured
    assert "Provider Status:    DEADLINE_EXCEEDED" in captured
    assert "Cleanup Status:     Warning - Secondary failure during cleanup (RuntimeError)" in captured
    assert "Aclose transport reset failure" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_cleanup_failure_on_success(mock_settings, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='{"name": "models/gemini-3.5-flash-lite"}',
            request=request,
        )

    def client_factory(api_key: str):
        c = create_client(api_key)
        c._api_client._async_httpx_client._transport = httpx.MockTransport(handler)
        c.aio.aclose = patch.object(c.aio, "aclose", side_effect=RuntimeError("Aclose reset failure on success")).start()
        return c

    code = await run_diagnostic(settings=mock_settings, client_factory=client_factory)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             FAILURE" in captured
    assert "Diagnostic Code:    CLEANUP_FAILURE" in captured
    assert "Provider Status:    OK" in captured
    assert "Cleanup Status:     Cleanup Failure: RuntimeError" in captured
    assert "Aclose reset failure on success" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_settings_load_failure(capsys):
    with patch("scripts.diagnose_gemini_metadata.get_settings", side_effect=ValueError("SecretEnvLoadError: /path/secret")):
        code = await run_diagnostic(settings=None)
        assert code == 1

        captured = capsys.readouterr().out
        assert "Result:             CONFIGURATION_ERROR" in captured
        assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
        assert "SecretEnvLoadError" not in captured


@pytest.mark.asyncio
async def test_metadata_diagnostic_missing_key(capsys):
    unconfigured_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    code = await run_diagnostic(settings=unconfigured_settings)
    assert code == 1

    captured = capsys.readouterr().out
    assert "Result:             CONFIGURATION_ERROR" in captured
    assert "Diagnostic Code:    CONFIGURATION_ERROR" in captured
    assert "AI_API_KEY is not configured" in captured
