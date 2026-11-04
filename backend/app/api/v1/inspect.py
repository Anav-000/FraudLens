from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.schemas.url_inspection import (
    UrlInspectionErrorResponse,
    UrlInspectionRequest,
    UrlInspectionResponse,
)
from app.services.url_inspector import UrlInspectionError, UrlInspectorService

router = APIRouter()
_url_inspector = UrlInspectorService()


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
