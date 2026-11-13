import asyncio
from datetime import datetime, timezone, timedelta
import logging
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.main import app
from app.schemas.capabilities import CapabilitiesResponse
from app.schemas.url_reputation import UrlReputationResponse
from app.services.safe_browsing import (
    SafeBrowsingService,
    UrlReputationError,
    SAFE_BROWSING_V5_URL,
    MAX_RESPONSE_BYTES,
    MAX_WARNING_FRESHNESS_SECONDS,
)
from app.services.url_inspector import UrlInspectorService

client = TestClient(app)

DUMMY_KEY = "test-google-safe-browsing-api-key-12345"


def get_mock_settings(configured: bool = True, version: str = "v5") -> Settings:
    """Helper to supply configured or unconfigured settings."""
    if configured:
        return Settings(
            safe_browsing_api_key=SecretStr(DUMMY_KEY),
            safe_browsing_version=version,
            ai_provider="none",
        )
    return Settings(
        safe_browsing_api_key=None,
        safe_browsing_version=version,
        ai_provider="none",
    )


@pytest.fixture(autouse=True)
def clean_dependencies_and_cache():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True, version="v5")
    get_settings.cache_clear()
    from app.api.v1.inspect import _safe_browsing
    _safe_browsing._cache.clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    _safe_browsing._cache.clear()


# -----------------------------------------------------------------------------
# Unit Tests for SafeBrowsingService & Validation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_unconfigured_raises_error():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=False)

    with pytest.raises(UrlReputationError) as exc_info:
        await service.check_reputation(
            raw_url="https://valid-domain.com/path",
            consent=True,
            settings=settings,
        )
    assert exc_info.value.code == "SERVICE_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert exc_info.value.reason == "provider_unconfigured"


@pytest.mark.asyncio
async def test_service_missing_consent_raises_error():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    with pytest.raises(UrlReputationError) as exc_info:
        await service.check_reputation(
            raw_url="https://valid-domain.com/path",
            consent=False,
            settings=settings,
        )
    assert exc_info.value.code == "CONSENT_REQUIRED"
    assert exc_info.value.http_status == 422


@pytest.mark.asyncio
async def test_service_rejects_embedded_credentials():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    with pytest.raises(UrlReputationError) as exc_info:
        await service.check_reputation(
            raw_url="https://admin:secret123@trusted.com/login",
            consent=True,
            settings=settings,
        )
    assert exc_info.value.code == "FORBIDDEN_DESTINATION"
    assert exc_info.value.reason == "embedded_credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_url, expected_reason",
    [
        ("http://127.0.0.1:8080/dashboard", "non_public_ip"),
        ("http://192.168.1.1/setup", "non_public_ip"),
        ("http://10.0.0.5/api", "non_public_ip"),
        ("http://[::1]:8080/page", "non_public_ip"),
        ("http://localhost:5000/app", "special_use_domain"),
        ("http://sub.localhost/test", "special_use_domain"),
        ("http://printer.local/status", "special_use_domain"),
        ("http://database.internal/query", "special_use_domain"),
        ("http://server.lan/index.html", "special_use_domain"),
        ("http://router/login", "special_use_domain"),
        ("http://test.invalid/verify", "special_use_domain"),
    ],
)
async def test_service_rejects_non_public_and_special_use_destinations(forbidden_url, expected_reason):
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    with pytest.raises(UrlReputationError) as exc_info:
        await service.check_reputation(
            raw_url=forbidden_url,
            consent=True,
            settings=settings,
        )
    assert exc_info.value.code == "FORBIDDEN_DESTINATION"
    assert exc_info.value.reason == expected_reason


@pytest.mark.asyncio
async def test_service_strips_fragment():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    checked_url, _ = service._strip_fragment_and_canonicalize(
        "https://public-destination.com/login?token=abc#user-section"
    )
    assert checked_url == "https://public-destination.com/login?token=abc"
    assert "#" not in checked_url


# -----------------------------------------------------------------------------
# Mocked Provider Lookup Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_threat_match():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"threats": [{"url": "https://public-domain.com/phish", "threatTypes": ["SOCIAL_ENGINEERING"]}], "cacheDuration": "300s"}'
    mock_resp.json.return_value = {
        "threats": [
            {
                "url": "https://public-domain.com/phish",
                "threatTypes": ["SOCIAL_ENGINEERING"],
            }
        ],
        "cacheDuration": "300s",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://public-domain.com/phish#top",
            consent=True,
            settings=settings,
        )

        assert res.status == "threat_match"
        assert res.provider == "Google Safe Browsing"
        assert res.threat_types == ["SOCIAL_ENGINEERING"]
        assert res.checked_url == "https://public-domain.com/phish"
        assert res.is_cached is False
        assert res.is_stale is False
        assert "SOCIAL_ENGINEERING" in res.summary
        assert "Data provided by Google Safe Browsing." in res.attribution
        assert res.expires_at is not None

        # Verify outbound call was made to Google endpoint only
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args[0] == SAFE_BROWSING_V5_URL
        assert kwargs["params"] == {"urls": "https://public-domain.com/phish"}
        assert kwargs["headers"]["x-goog-api-key"] == DUMMY_KEY


@pytest.mark.asyncio
async def test_service_no_known_match():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration": "600s"}'
    mock_resp.json.return_value = {
        "cacheDuration": "600s",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://clean-site.org/home",
            consent=True,
            settings=settings,
        )

        assert res.status == "no_known_match"
        assert res.threat_types == []
        assert res.is_cached is False
        assert res.is_stale is False
        assert res.summary == "No known threat match was returned. This does not prove the URL is safe."
        assert "Data provided by Google Safe Browsing." in res.attribution


@pytest.mark.asyncio
async def test_service_no_known_match_empty_body():
    """
    An empty HTTP 200 body is invalid JSON and must fail closed.
    """
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.text = ""

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://example.com/",
            consent=True,
            settings=settings,
        )

        assert res.status == "unavailable"
        assert res.threat_types == []
        assert res.error_code == "MALFORMED_PROVIDER_RESPONSE"
        assert res.is_cached is False
        assert res.is_stale is False
        assert "No known threat match was returned" not in res.summary
        assert res.expires_at is None


@pytest.mark.asyncio
async def test_service_no_known_match_whitespace_body():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"   \n"
    mock_resp.text = "   \n"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://example.com/",
            consent=True,
            settings=settings,
        )

        assert res.status == "unavailable"
        assert res.threat_types == []


@pytest.mark.asyncio
async def test_service_no_known_match_empty_json_object():
    """Empty JSON object with omitted cacheDuration and threats."""
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"{}"
    mock_resp.text = "{}"
    mock_resp.json.return_value = {}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://example.com/",
            consent=True,
            settings=settings,
        )

        assert res.status == "no_known_match"
        assert res.threat_types == []
        assert res.expires_at is None
        assert res.is_expired() is False


@pytest.mark.asyncio
async def test_service_no_known_match_http_204():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.content = b""
    mock_resp.text = ""

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://example.com/",
            consent=True,
            settings=settings,
        )

        assert res.status == "unavailable"
        assert res.threat_types == []


@pytest.mark.asyncio
async def test_service_threat_match_with_snake_case_fields():
    """Proto3 JSON mapping with snake_case preserving_proto_field_name."""
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"threats": [{"url": "https://malicious.com", "threat_types": ["MALWARE"]}], "cache_duration": "400s"}'
    mock_resp.text = '{"threats": [{"url": "https://malicious.com", "threat_types": ["MALWARE"]}], "cache_duration": "400s"}'
    mock_resp.json.return_value = {
        "threats": [{"url": "https://malicious.com", "threat_types": ["MALWARE"]}],
        "cache_duration": "400s",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://malicious.com",
            consent=True,
            settings=settings,
        )

        assert res.status == "threat_match"
        assert res.threat_types == ["MALWARE"]


@pytest.mark.asyncio
async def test_service_numeric_cache_duration():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration": 120}'
    mock_resp.text = '{"cacheDuration": 120}'
    mock_resp.json.return_value = {"cacheDuration": 120}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://clean-site.org",
            consent=True,
            settings=settings,
        )

        assert res.status == "unavailable"


@pytest.mark.asyncio
async def test_service_non_dict_json_payload_rejected_as_malformed():
    """A valid JSON array or primitive is not a valid Safe Browsing response object."""
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'[1, 2, 3]'
    mock_resp.text = '[1, 2, 3]'
    mock_resp.json.return_value = [1, 2, 3]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation(
            raw_url="https://clean-site.org",
            consent=True,
            settings=settings,
        )

        assert res.status == "unavailable"
        assert res.error_code == "MALFORMED_PROVIDER_RESPONSE"
        assert res.status != "no_known_match"


@pytest.mark.asyncio
async def test_service_caching_and_freshness():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration": "300s"}'
    mock_resp.json.return_value = {"cacheDuration": "300s"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        # First request: fetches from provider
        res1 = await service.check_reputation("https://test-cache.com/path", True, settings)
        assert res1.is_cached is False
        assert mock_get.call_count == 1

        # Second request: served from in-memory cache
        res2 = await service.check_reputation("https://test-cache.com/path", True, settings)
        assert res2.is_cached is True
        assert res2.is_stale is False
        assert mock_get.call_count == 1  # No second outbound HTTP call


@pytest.mark.asyncio
async def test_service_warning_freshness_stale_flag():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"threats": [{"url": "https://threat-site.com", "threatTypes": ["MALWARE"]}], "cacheDuration": "1800s"}'
    mock_resp.json.return_value = {
        "threats": [{"url": "https://threat-site.com", "threatTypes": ["MALWARE"]}],
        "cacheDuration": "1800s",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res1 = await service.check_reputation("https://threat-site.com", True, settings)
        assert res1.is_cached is False
        assert res1.is_stale is False

        # Simulate time jump: 31 minutes later (older than 30-minute freshness rule)
        now_31m_later = datetime.now(timezone.utc) + timedelta(minutes=31)
        res_stale = await service._lookup_cache(
            list(service._cache.keys())[0],
            now_31m_later,
        )
        # Contract: Expired entries must not be reused as current; evicted from cache
        assert res_stale is None
        assert len(service._cache) == 0

        # Separately verify displayed results become stale after their deadline
        assert now_31m_later >= datetime.fromisoformat(res1.expires_at)
        assert res1.is_expired(now_31m_later) is True
        displayed_stale = res1.mark_stale_if_expired(now_31m_later)
        assert displayed_stale.is_stale is True


@pytest.mark.asyncio
async def test_service_cached_negative_entry_becomes_stale_before_expiry():
    """
    Verifies that for responses with cache duration exceeding 30 minutes (e.g. negative cache),
    _lookup_cache retains the cached entry but flags it as is_stale=True once past
    MAX_WARNING_FRESHNESS_SECONDS.
    """
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration": "3600s"}'
    mock_resp.json.return_value = {"cacheDuration": "3600s"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res1 = await service.check_reputation("https://clean-site.org", True, settings)
        assert res1.is_cached is False
        assert res1.is_stale is False

        # 15 minutes later: cached and fresh
        now_15m_later = datetime.now(timezone.utc) + timedelta(minutes=15)
        res_15m = await service._lookup_cache(list(service._cache.keys())[0], now_15m_later)
        assert res_15m is not None
        assert res_15m.is_cached is True
        assert res_15m.is_stale is False

        # 31 minutes later: cached but stale (past 30-minute freshness rule, before 60-minute expiry)
        now_31m_later = datetime.now(timezone.utc) + timedelta(minutes=31)
        res_31m = await service._lookup_cache(list(service._cache.keys())[0], now_31m_later)
        assert res_31m is not None
        assert res_31m.is_cached is True
        assert res_31m.is_stale is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_error_code",
    [
        (400, "PROVIDER_REQUEST_ERROR"),
        (403, "PROVIDER_AUTHENTICATION_FAILED"),
        (429, "PROVIDER_QUOTA_EXCEEDED"),
        (500, "PROVIDER_SERVER_ERROR"),
        (503, "PROVIDER_SERVER_ERROR"),
    ],
)
async def test_service_http_errors_never_become_no_match(status_code, expected_error_code):
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.content = b'{"error": "Simulated error"}'

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation("https://target.com/page", True, settings)

        assert res.status == "unavailable"
        assert res.error_code == expected_error_code
        assert res.threat_types == []
        assert "No known threat match was returned" not in res.summary


@pytest.mark.asyncio
async def test_service_timeout_never_becomes_no_match():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connection timed out")
        res = await service.check_reputation("https://target.com/slow", True, settings)

        assert res.status == "unavailable"
        assert res.error_code == "PROVIDER_TIMEOUT"
        assert "timed out" in res.summary.lower()


@pytest.mark.asyncio
async def test_service_network_error_never_becomes_no_match():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.NetworkError("DNS failure to googleapis")
        res = await service.check_reputation("https://target.com/net-err", True, settings)

        assert res.status == "unavailable"
        assert res.error_code == "PROVIDER_NETWORK_ERROR"


@pytest.mark.asyncio
async def test_service_malformed_json_never_becomes_no_match():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'<html><body>Not JSON</body></html>'
    mock_resp.json.side_effect = __import__("json").JSONDecodeError("Invalid JSON", "", 0)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation("https://target.com/broken", True, settings)

        assert res.status == "unavailable"
        assert res.error_code == "MALFORMED_PROVIDER_RESPONSE"


@pytest.mark.asyncio
async def test_service_oversized_response_bounded():
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Create content exceeding MAX_RESPONSE_BYTES (64 KiB)
    mock_resp.content = b"x" * (MAX_RESPONSE_BYTES + 100)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_reputation("https://target.com/huge", True, settings)

        assert res.status == "unavailable"
        assert res.error_code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_sensitive_log_redaction(caplog):
    service = SafeBrowsingService()
    settings = get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration": "300s"}'
    mock_resp.json.return_value = {"cacheDuration": "300s"}

    secret_url = "https://confidential-domain.com/path?secret_token=9988776655"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with caplog.at_level(logging.INFO):
            await service.check_reputation(secret_url, True, settings)

        for record in caplog.records:
            assert "secret_token" not in record.message
            assert DUMMY_KEY not in record.message
            assert "9988776655" not in record.message


# -----------------------------------------------------------------------------
# API Route Integration Tests (POST /api/v1/inspect/url/reputation)
# -----------------------------------------------------------------------------


def test_api_reputation_unconfigured():
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=False)
    response = client.post(
        "/api/v1/inspect/url/reputation",
        json={"url": "https://public-example.org", "consent": True},
    )
    assert response.status_code == 503
    data = response.json()
    assert data["code"] == "SERVICE_UNAVAILABLE"
    assert response.headers.get("Cache-Control") == "no-store"


def test_api_reputation_missing_consent():
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)
    response = client.post(
        "/api/v1/inspect/url/reputation",
        json={"url": "https://public-example.org", "consent": False},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "CONSENT_REQUIRED"
    assert response.headers.get("Cache-Control") == "no-store"


def test_api_reputation_forbidden_destination():
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)
    response = client.post(
        "/api/v1/inspect/url/reputation",
        json={"url": "http://127.0.0.1:8000/api", "consent": True},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "FORBIDDEN_DESTINATION"
    assert response.headers.get("Cache-Control") == "no-store"


def test_api_reputation_threat_match_success():
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"threats": [{"url": "https://malicious.com", "threatTypes": ["MALWARE"]}], "cacheDuration": "300s"}'
    mock_resp.json.return_value = {
        "threats": [{"url": "https://malicious.com", "threatTypes": ["MALWARE"]}],
        "cacheDuration": "300s",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://malicious.com#frag", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "threat_match"
        assert data["threat_types"] == ["MALWARE"]
        assert data["checked_url"] == "https://malicious.com/"
        assert response.headers.get("Cache-Control") == "no-store"


def test_api_reputation_empty_body_clean_url():
    """An empty provider body must remain unavailable through the API route."""
    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.text = ""

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://example.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["threat_types"] == []
        assert data["checked_url"] == "https://example.com/"
        assert response.headers.get("Cache-Control") == "no-store"


def test_capabilities_truthfully_reports_safe_browsing():
    with patch("app.api.v1.capabilities.check_ocr_availability", return_value=(False, [], "missing_prerequisites")):
        # When unconfigured
        app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=False)
        get_settings.cache_clear()
        res = client.get("/api/v1/capabilities")
        assert res.status_code == 200
        assert res.json()["url_reputation"] is False

        # When configured
        app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)
        get_settings.cache_clear()
        res = client.get("/api/v1/capabilities")
        assert res.status_code == 200
        assert res.json()["url_reputation"] is True


def test_endpoint_binary_protobuf_returns_service_unavailable():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"\x0a\x19\x0a\x14https://example.com/\x12\x01\x01\x12\x03\x08\xac\x02"
    mock_resp.headers = {"content-type": "application/x-protobuf"}

    app.dependency_overrides[get_settings] = lambda: get_mock_settings(configured=True)
    get_settings.cache_clear()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://example.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["error_code"] == "MALFORMED_PROVIDER_RESPONSE"
        assert data["error_reason"] == "unverified_binary_schema"
        assert data["threat_types"] == []


def test_endpoint_v4_valid_threat_match():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"matches":[{"threatType":"MALWARE","cacheDuration":"300s"}]}'
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "matches": [{"threatType": "MALWARE", "cacheDuration": "300s"}]
    }

    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://malware-v4.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "threat_match"
        assert data["threat_types"] == ["MALWARE"]
        assert data["is_cached"] is False
        assert mock_post.call_count == 1

        # Second request: served from cache
        response2 = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://malware-v4.com/", "consent": True},
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] == "threat_match"
        assert data2["is_cached"] is True
        assert mock_post.call_count == 1


def test_endpoint_v4_valid_no_match():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"{}"
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {}

    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://safe-v4.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_known_match"
        assert data["threat_types"] == []
        assert data["expires_at"] is None
        assert data["is_cached"] is False
        assert mock_post.call_count == 1

        # Second request: since {} does not use an invented 300s TTL, it is not cached
        response2 = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://safe-v4.com/", "consent": True},
        )
        assert response2.status_code == 200
        assert response2.json()["is_cached"] is False
        assert mock_post.call_count == 2


def test_endpoint_v4_no_match_explicit_cache_duration():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"cacheDuration":"120s"}'
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"cacheDuration": "120s"}

    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://safe-v4-duration.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_known_match"
        assert data["expires_at"] is not None
        assert data["is_cached"] is False
        assert mock_post.call_count == 1


def test_endpoint_v4_provider_error_never_no_known_match():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = b'{"error":"Internal error"}'
    mock_resp.headers = {"content-type": "application/json"}

    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = client.post(
            "/api/v1/inspect/url/reputation",
            json={"url": "https://error-v4.com/", "consent": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["status"] != "no_known_match"
        assert data["error_code"] == "PROVIDER_SERVER_ERROR"


def test_endpoint_v4_consent_required():
    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    response = client.post(
        "/api/v1/inspect/url/reputation",
        json={"url": "https://example.com/", "consent": False},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "CONSENT_REQUIRED"


def test_endpoint_v4_rejects_embedded_credentials():
    v4_settings = Settings(
        safe_browsing_api_key=SecretStr(DUMMY_KEY),
        safe_browsing_version="v4",
        ai_provider="none",
    )
    app.dependency_overrides[get_settings] = lambda: v4_settings
    get_settings.cache_clear()

    response = client.post(
        "/api/v1/inspect/url/reputation",
        json={"url": "https://admin:secret@example.com/", "consent": True},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "FORBIDDEN_DESTINATION"
    assert data["reason"] == "embedded_credentials"
