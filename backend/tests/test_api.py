from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.core.config import Settings, get_settings
from app.schemas.analysis import TextAnalysisResponse, WarningSign
from app.services.gemini import GeminiAdapterError, GeminiErrorCode


@pytest.fixture
def default_client():
    isolated_settings = Settings(
        ai_provider="none",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: isolated_settings
    return TestClient(app)


@pytest.fixture
def configured_client():
    configured_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=SecretStr("AIzaSyMockKeyForTestingAnalysisApi123"),
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: configured_settings
    return TestClient(app)


def test_health_endpoint(default_client):
    response = default_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "ok",
        "service": "fraudlens-api",
    }


def test_capabilities_defaults(default_client):
    with patch("app.api.v1.capabilities.check_ocr_availability", return_value=(False, [], "missing_prerequisites")):
        response = default_client.get("/api/v1/capabilities")
        assert response.status_code == 200
        data = response.json()
        # In Phase 2B/3A, text_analysis capability is implemented
        assert data["text_analysis"] is True
        assert data["screenshot_extraction"] is False
        assert data["url_reputation"] is False
        assert data["saved_cases"] is False
        assert data["ai_connection"] == "not_tested"
        assert data["ai_configuration"] == "missing"
        assert data["ocr_prerequisite_status"] == "missing_prerequisites"


def test_capabilities_reports_present_when_configured(configured_client):
    response = configured_client.get("/api/v1/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["text_analysis"] is True
    assert data["ai_configuration"] == "present"
    assert data["ai_connection"] == "not_tested"


def test_capabilities_no_secret_leak():
    secret_key = "SECRET_AI_KEY_TEST_DO_NOT_LEAK"
    custom_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=SecretStr(secret_key),
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: custom_settings
    client = TestClient(app)

    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["ai_configuration"] == "present"
    assert data["ai_connection"] == "not_tested"
    assert secret_key not in response.text


def test_text_analysis_rejects_blank_and_whitespace(default_client):
    # Empty string
    res_empty = default_client.post("/api/v1/analyze/text", json={"text": ""})
    assert res_empty.status_code == 422
    assert res_empty.json()["code"] == "VALIDATION_ERROR"

    # Whitespace only
    res_spaces = default_client.post("/api/v1/analyze/text", json={"text": "   \n\t  "})
    assert res_spaces.status_code == 422
    assert res_spaces.json()["code"] == "VALIDATION_ERROR"


def test_text_analysis_rejects_over_limit(default_client):
    oversized_text = "a" * 10001
    response = default_client.post("/api/v1/analyze/text", json={"text": oversized_text})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_text_analysis_rejects_unsupported_language(default_client):
    response = default_client.post(
        "/api/v1/analyze/text",
        json={"text": "Valid suspicious message", "language": "fr"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_text_analysis_rejects_unexpected_fields(default_client):
    response = default_client.post(
        "/api/v1/analyze/text",
        json={
            "text": "Valid suspicious message",
            "language": "en",
            "unexpected_field": "should_fail",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_validation_errors_do_not_echo_submitted_marker(default_client):
    distinctive_marker = "DISTINCTIVE_SENSITIVE_CONTENT_12345"

    # Case 1: Marker in oversized payload
    oversized_with_marker = f"{distinctive_marker} " + ("x" * 10000)
    res_oversized = default_client.post("/api/v1/analyze/text", json={"text": oversized_with_marker})
    assert res_oversized.status_code == 422
    assert distinctive_marker not in res_oversized.text

    # Case 2: Marker in unexpected field
    res_unexpected = default_client.post(
        "/api/v1/analyze/text",
        json={"text": "Valid message", "leak_test": distinctive_marker},
    )
    assert res_unexpected.status_code == 422
    assert distinctive_marker not in res_unexpected.text


def test_analyze_text_missing_configuration_returns_503(default_client):
    response = default_client.post(
        "/api/v1/analyze/text",
        json={"text": "Suspicious job offer asking for fee payment", "language": "en"},
    )
    assert response.status_code == 503
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "AI_CONFIGURATION_MISSING"


def test_no_ai_provider_call_attempted_on_invalid_input(monkeypatch, default_client):
    # Verify no outbound HTTP calls happen when validation fails
    import httpx

    def forbidden_request(*args, **kwargs):
        raise AssertionError("Outbound network call was attempted!")

    monkeypatch.setattr(httpx, "get", forbidden_request)
    monkeypatch.setattr(httpx, "post", forbidden_request)

    response = default_client.post(
        "/api/v1/analyze/text",
        json={"text": "", "language": "en"},
    )
    assert response.status_code == 422


def test_analyze_text_success_returns_200_and_no_store(configured_client):
    sample_response = TextAnalysisResponse(
        assessment="warning_signs_found",
        category="job",
        summary="This message is an advance-fee job scam.",
        warning_signs=[
            WarningSign(
                title="Upfront Fee Required",
                evidence_quote="pay $50 registration fee",
                explanation="Legitimate employers do not charge applicants a fee to apply.",
            )
        ],
        uncertainties=["Sender identity cannot be established from text alone."],
        verification_steps=["Contact the official company HR department through their website."],
        language="en",
        analysis_basis="submitted_text_only",
        external_checks_performed=False,
        limitation="This assessment is generated by an AI model based solely on the submitted text.",
    )

    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = sample_response

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Earn $500/day! Just pay $50 registration fee to begin.", "language": "en"},
        )
        assert response.status_code == 200
        assert response.headers.get("Cache-Control") == "no-store"

        data = response.json()
        assert data["assessment"] == "warning_signs_found"
        assert data["category"] == "job"
        assert data["summary"] == "This message is an advance-fee job scam."
        assert len(data["warning_signs"]) == 1
        assert data["warning_signs"][0]["evidence_quote"] == "pay $50 registration fee"
        assert data["analysis_basis"] == "submitted_text_only"
        assert data["external_checks_performed"] is False


def test_analyze_text_invalid_ai_response_returns_502(configured_client):
    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = GeminiAdapterError(
            code=GeminiErrorCode.INVALID_RESPONSE,
            reason="EVIDENCE_MISMATCH",
            message="Evidence quote is not an exact substring of submitted text.",
            action="Reject fabricated model citations.",
            stage="evidence_validation",
        )

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Some text here", "language": "en"},
        )
        assert response.status_code == 502
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "INVALID_AI_RESPONSE"
        assert data["reason"] == "EVIDENCE_MISMATCH"
        assert data["message"] == "Evidence quote is not an exact substring of submitted text."
        assert data["action"] == "Reject fabricated model citations."


def test_analyze_text_quota_exceeded_returns_429(configured_client):
    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = GeminiAdapterError(
            code=GeminiErrorCode.QUOTA_EXCEEDED,
            message="Rate limit exceeded.",
            action="Check quota.",
            stage="request",
        )

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Some text here", "language": "en"},
        )
        assert response.status_code == 429
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.json()["code"] == "AI_QUOTA_EXCEEDED"


def test_analyze_text_timeout_returns_504(configured_client):
    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = GeminiAdapterError(
            code=GeminiErrorCode.NETWORK_TIMEOUT,
            message="Client timed out.",
            action="Check connectivity.",
            stage="request",
        )

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Some text here", "language": "en"},
        )
        assert response.status_code == 504
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.json()["code"] == "AI_NETWORK_TIMEOUT"


def test_analyze_text_auth_failed_returns_503(configured_client):
    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = GeminiAdapterError(
            code=GeminiErrorCode.AUTH_FAILED,
            message="Authentication failed.",
            action="Verify key.",
            stage="request",
        )

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Some text here", "language": "en"},
        )
        assert response.status_code == 503
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.json()["code"] == "AI_AUTH_FAILED"


def test_analyze_text_request_rejected_returns_502_ai_request_rejected(configured_client):
    with patch("app.api.v1.analysis.GeminiAdapter.analyze_message", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = GeminiAdapterError(
            code=GeminiErrorCode.REQUEST_REJECTED,
            reason="INVALID_SCHEMA_DEFINITION",
            message="Gemini API rejected request with client error (HTTP 400, status: INVALID_ARGUMENT). Rejected field(s): generation_config.response_schema.additional_properties.",
            action="Verify model generation configuration and structured output schema compatibility.",
            stage="request",
            http_status=400,
            provider_status="INVALID_ARGUMENT",
        )

        response = configured_client.post(
            "/api/v1/analyze/text",
            json={"text": "Some text here", "language": "en"},
        )
        assert response.status_code == 502
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "AI_REQUEST_REJECTED"
        assert data["reason"] == "INVALID_SCHEMA_DEFINITION"
        assert "Rejected field(s): generation_config.response_schema.additional_properties" in data["message"]
        assert data["action"] == "Verify model generation configuration and structured output schema compatibility."
