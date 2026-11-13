from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.schemas.url_inspection import (
    UrlInspectionErrorResponse,
    UrlInspectionRequest,
    UrlInspectionResponse,
)
from app.schemas.url_reputation import (
    UrlReputationErrorResponse,
    UrlReputationRequest,
    UrlReputationResponse,
)
from app.services.safe_browsing import SafeBrowsingService, UrlReputationError
from app.services.url_inspector import UrlInspectionError, UrlInspectorService

router = APIRouter()
_url_inspector = UrlInspectorService()
_safe_browsing = SafeBrowsingService(inspector=_url_inspector)


@router.post(
    "/inspect/url",
    response_model=UrlInspectionResponse,
    responses={
        200: {
            "model": UrlInspectionResponse,
            "description": "Structured outcome of local offline URL structure inspection.",
        },
        422: {
            "model": UrlInspectionErrorResponse,
            "description": "URL validation or formatting failure (sanitized).",
        },
        500: {
            "model": UrlInspectionErrorResponse,
            "description": "Internal server error.",
        },
    },
    tags=["URL Inspection"],
)
async def inspect_url(request: UrlInspectionRequest) -> Response:
    """
    Performs purely local, offline URL structure inspection.
    Enforces strict zero-network boundary: no DNS resolution, no HTTP/HTTPS requests,
    no external reputation lookups, and no AI provider calls.
    Submitted URLs are never logged or persisted.
    Applies Cache-Control: no-store on all responses.
    """
    try:
        result = _url_inspector.inspect_url(request.url)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except UrlInspectionError as err:
        error_content = {
            "code": err.code,
            "message": err.message,
            "action": err.action,
        }
        if err.reason:
            error_content["reason"] = err.reason

        return JSONResponse(
            status_code=err.http_status,
            content=error_content,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        exc_class = type(exc).__name__
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": f"An unexpected error occurred during URL inspection ({exc_class}).",
                "action": "Verify URL format and retry.",
            },
            headers={"Cache-Control": "no-store"},
        )


@router.post(
    "/inspect/url/reputation",
    response_model=UrlReputationResponse,
    responses={
        200: {
            "model": UrlReputationResponse,
            "description": "Structured outcome of Google Safe Browsing reputation lookup.",
        },
        422: {
            "model": UrlReputationErrorResponse,
            "description": "Validation failure, missing consent, or forbidden destination.",
        },
        503: {
            "model": UrlReputationErrorResponse,
            "description": "Safe Browsing is unconfigured or unavailable.",
        },
        500: {
            "model": UrlReputationErrorResponse,
            "description": "Internal server error.",
        },
    },
    tags=["URL Reputation"],
)
async def check_url_reputation(
    request: UrlReputationRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Checks URL reputation against Google Safe Browsing v5 urls.search.
    Requires explicit user consent and server SAFE_BROWSING_API_KEY configuration.
    Validates destination without DNS resolution and rejects non-public/special-use destinations.
    Enforces in-memory hashed caching, bounded 10s deadline, and zero automatic retries.
    Applies Cache-Control: no-store on all responses.
    """
    try:
        result = await _safe_browsing.check_reputation(
            raw_url=request.url,
            consent=request.consent,
            settings=settings,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except (UrlReputationError, UrlInspectionError) as err:
        error_content = {
            "code": err.code,
            "message": err.message,
            "action": err.action,
        }
        if getattr(err, "reason", None):
            error_content["reason"] = err.reason

        return JSONResponse(
            status_code=err.http_status,
            content=error_content,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        exc_class = type(exc).__name__
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": f"An unexpected error occurred during URL reputation check ({exc_class}).",
                "action": "Verify URL format and retry.",
            },
            headers={"Cache-Control": "no-store"},
        )
