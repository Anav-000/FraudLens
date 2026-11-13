from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.api.v1.analysis import router as analysis_router
from app.api.v1.capabilities import router as capabilities_router
from app.api.v1.extract import router as extract_router
from app.api.v1.health import router as health_router
from app.api.v1.inspect import router as inspect_router
from app.core.config import get_settings
from app.middleware.upload_limits import BoundedUploadMiddleware


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="FraudLens API",
        description="Backend API service for FraudLens verification workflows.",
        version="0.1.0",
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url=None,
    )

    # Middleware execution order in Starlette/FastAPI: last added is outermost.
    # We want BoundedUploadMiddleware to intercept streaming chunks before multipart parsing.
    app.add_middleware(BoundedUploadMiddleware)

    # CORS configuration - strict origin matching, no wildcards, no unnecessary credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # Custom multipart exception handler for malformed parts or part count limits
    @app.exception_handler(MultiPartException)
    async def multipart_exception_handler(
        request: Request, exc: MultiPartException
    ) -> JSONResponse:
        path = request.scope.get("path", "")
        action = (
            "Upload a single PDF document file."
            if "document" in path
            else "Upload a single PNG or JPEG screenshot with an optional ocr_language field."
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "code": "INVALID_MULTIPART_REQUEST",
                "message": "The multipart request payload was invalid or exceeded allowed part boundaries.",
                "action": action,
            },
            headers={"Cache-Control": "no-store"},
        )

    # Handler for Starlette/FastAPI HTTPExceptions (e.g. multipart part limits)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        headers = {"Cache-Control": "no-store"}
        if exc.headers:
            headers.update(exc.headers)

        # Detect abort caused by streamed payload size overflow
        if request.scope.get("payload_too_large"):
            path = request.scope.get("path", "")
            action = (
                "Compress or split the PDF document before uploading."
                if "document" in path
                else "Compress, crop, or resize the screenshot before uploading."
            )
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "code": "FILE_TOO_LARGE",
                    "message": (
                        "Streamed request body exceeded the maximum allowed size limit of "
                        "5 MiB (with 64 KiB multipart overhead)."
                    ),
                    "action": action,
                },
                headers=headers,
            )

        detail_str = str(exc.detail)
        code = (
            "INVALID_MULTIPART_REQUEST"
            if "maximum number of" in detail_str.lower() or "multipart" in detail_str.lower()
            else "BAD_REQUEST"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": code,
                "message": detail_str,
                "action": "Ensure request payload complies with size and parameter limits.",
            },
            headers=headers,
        )

    # Custom validation exception handler that sanitizes errors
    # Guarantees user-submitted input values or sensitive markers are never echoed back
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        sanitized_details = [
            {
                "loc": [str(loc_item) for loc_item in err.get("loc", [])],
                "msg": err.get("msg", "Validation error"),
                "type": err.get("type", "validation_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "VALIDATION_ERROR",
                "message": "The request payload failed validation.",
                "details": sanitized_details,
            },
            headers={"Cache-Control": "no-store"},
        )

    # Register routers under /api/v1
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(capabilities_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(extract_router, prefix="/api/v1")
    app.include_router(inspect_router, prefix="/api/v1")

    # Root health-check alias for load balancers and platform monitors
    @app.get("/health", include_in_schema=False)
    def root_health() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "service": "fraudlens-api"},
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
