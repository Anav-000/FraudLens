from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.schemas.analysis import (
    ErrorResponse,
    TextAnalysisRequest,
    TextAnalysisResponse,
)
from app.services.gemini import GeminiAdapter, GeminiAdapterError, GeminiErrorCode

router = APIRouter()


def map_adapter_error_to_http(err: GeminiAdapterError) -> tuple[int, str]:
    """
    Maps sanitized GeminiAdapterError to an appropriate HTTP status code and stable application error code.
    Never exposes raw exceptions, provider payloads, or sensitive markers.
    """
    if err.code == GeminiErrorCode.CONFIGURATION_MISSING:
        return status.HTTP_503_SERVICE_UNAVAILABLE, "AI_CONFIGURATION_MISSING"
    if err.code == GeminiErrorCode.AUTH_FAILED:
        return status.HTTP_503_SERVICE_UNAVAILABLE, "AI_AUTH_FAILED"
    if err.code == GeminiErrorCode.MODEL_UNAVAILABLE:
        return status.HTTP_503_SERVICE_UNAVAILABLE, "AI_MODEL_UNAVAILABLE"
    if err.code == GeminiErrorCode.QUOTA_EXCEEDED:
        return status.HTTP_429_TOO_MANY_REQUESTS, "AI_QUOTA_EXCEEDED"
    if err.code == GeminiErrorCode.NETWORK_TIMEOUT:
        return status.HTTP_504_GATEWAY_TIMEOUT, "AI_NETWORK_TIMEOUT"
    if err.code == GeminiErrorCode.PROVIDER_DEADLINE_EXCEEDED:
        return status.HTTP_504_GATEWAY_TIMEOUT, "AI_PROVIDER_DEADLINE_EXCEEDED"
    if err.code == GeminiErrorCode.PROVIDER_UNAVAILABLE:
        return status.HTTP_503_SERVICE_UNAVAILABLE, "AI_PROVIDER_UNAVAILABLE"
    if err.code == GeminiErrorCode.REQUEST_REJECTED:
        return status.HTTP_502_BAD_GATEWAY, "AI_REQUEST_REJECTED"
    if err.code == GeminiErrorCode.INVALID_RESPONSE:
        return status.HTTP_502_BAD_GATEWAY, "INVALID_AI_RESPONSE"
    return status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_SERVER_ERROR"


@router.post(
    "/analyze/text",
    response_model=TextAnalysisResponse,
    responses={
        200: {"model": TextAnalysisResponse, "description": "Structured message assessment."},
        422: {"model": ErrorResponse, "description": "Validation error (sanitized)."},
        429: {"model": ErrorResponse, "description": "AI provider rate limit or quota exceeded."},
        502: {"model": ErrorResponse, "description": "Invalid AI response or evidence quote mismatch."},
        503: {"model": ErrorResponse, "description": "AI service or configuration unavailable."},
        504: {"model": ErrorResponse, "description": "Network timeout or provider deadline exceeded."},
        500: {"model": ErrorResponse, "description": "Internal server error."},
    },
    tags=["Analysis"],
)
async def analyze_text(
    request: TextAnalysisRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Analyzes untrusted message text using the Gemini adapter.
    Enforces exact evidence quote validation, cross-field consistency, and Cache-Control: no-store.
    No user content is logged or persisted.
    """
    adapter = GeminiAdapter(settings)
    try:
        result = await adapter.analyze_message(text=request.text, language=request.language)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except GeminiAdapterError as err:
        http_status, error_code = map_adapter_error_to_http(err)
        error_content = {
            "code": error_code,
            "message": err.message,
            "action": err.action,
        }
        if err.reason:
            error_content["reason"] = err.reason
        return JSONResponse(
            status_code=http_status,
            content=error_content,
            headers={"Cache-Control": "no-store"},
        )
