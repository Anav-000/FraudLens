import httpx
import pytest
from google import genai
from google.genai import types
from google.genai._gaos.utils.retries import RetryConfig

from scripts.diagnose_raw_gemini import create_client, create_content_config
from scripts.diagnose_gemini_interactions import create_configured_client, CONFIGURED_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_generate_content_transport_single_attempt_on_503():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        # Safe assertion on requested Google endpoint
        assert "generativelanguage.googleapis.com" in str(request.url)
        assert "/v1beta/models/gemini-3.5-flash-lite:generateContent" in str(request.url)
        return httpx.Response(
            503,
            text='{"error": {"code": 503, "status": "UNAVAILABLE", "message": "Service unavailable"}}',
            request=request,
        )

    client = create_client("fake-test-api-key")
    client._api_client._async_httpx_client._transport = httpx.MockTransport(handler)

    try:
        await client.aio.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents="Reply with the word Hello.",
            config=create_content_config(),
        )
    except Exception:
        pass
    finally:
        await client.aio.aclose()

    assert attempts == 1


@pytest.mark.asyncio
async def test_generate_content_transport_single_attempt_on_timeout():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert "generativelanguage.googleapis.com" in str(request.url)
        raise httpx.ReadTimeout("Mocked transport timeout", request=request)

    client = create_client("fake-test-api-key")
    client._api_client._async_httpx_client._transport = httpx.MockTransport(handler)

    try:
        await client.aio.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents="Reply with the word Hello.",
            config=create_content_config(),
        )
    except Exception:
        pass
    finally:
        await client.aio.aclose()

    assert attempts == 1


def test_interactions_transport_single_attempt_on_503():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert "generativelanguage.googleapis.com" in str(request.url)
        assert "/v1beta/interactions" in str(request.url)
        return httpx.Response(
            503,
            text='{"error": {"code": "UNAVAILABLE", "message": "Service unavailable"}}',
            request=request,
        )

    client = create_configured_client("fake-test-api-key")
    client._api_client._httpx_client._transport = httpx.MockTransport(handler)

    try:
        client.interactions.create(
            model="gemini-3.5-flash-lite",
            input="Reply with the word Hello.",
            store=False,
            generation_config={"thinking_level": "medium"},
            timeout=CONFIGURED_TIMEOUT_SECONDS,
        )
    except Exception:
        pass
    finally:
        client.close()

    assert attempts == 1


def test_interactions_transport_single_attempt_on_timeout():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert "generativelanguage.googleapis.com" in str(request.url)
        raise httpx.ReadTimeout("Mocked transport timeout", request=request)

    client = create_configured_client("fake-test-api-key")
    client._api_client._httpx_client._transport = httpx.MockTransport(handler)

    try:
        client.interactions.create(
            model="gemini-3.5-flash-lite",
            input="Reply with the word Hello.",
            store=False,
            generation_config={"thinking_level": "medium"},
            timeout=CONFIGURED_TIMEOUT_SECONDS,
        )
    except Exception:
        pass
    finally:
        client.close()

    assert attempts == 1
