"""
Middleware for strictly bounding request body size and multipart uploads
prior to Starlette / python-multipart spooling to disk.
"""
from typing import Callable, Awaitable
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Enforced maximum sizes
MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB image payload
MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024  # 64 KiB allowance for boundary, headers, form fields
MAX_MULTIPART_REQUEST_SIZE = MAX_IMAGE_FILE_SIZE + MULTIPART_OVERHEAD_ALLOWANCE  # 5,308,416 bytes (~5.06 MiB)


class StreamingPayloadTooLargeError(Exception):
    """Raised when incoming streamed body chunks exceed the byte limit."""
    pass


class BoundedUploadMiddleware:
    """
    ASGI middleware that bounds request body sizes before or during streaming.
    Guarantees:
    1. Explicit Content-Length exceeding MAX_MULTIPART_REQUEST_SIZE is rejected with HTTP 413
       immediately, without reading or spooling a single body byte.
    2. Missing, chunked, or misleading Content-Length headers are tracked per chunk during streaming.
       If cumulative bytes exceed MAX_MULTIPART_REQUEST_SIZE, streaming is aborted immediately with HTTP 413.
    3. Rejection responses include Cache-Control: no-store and sanitized error codes.
    """
    def __init__(
        self,
        app: ASGIApp,
        max_upload_size: int = MAX_MULTIPART_REQUEST_SIZE,
    ):
        self.app = app
        self.max_upload_size = max_upload_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Apply strict body bounds to extraction upload routes (screenshot and document)
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if method == "POST" and path in ("/api/v1/extract/screenshot", "/api/v1/extract/document"):
            headers = Headers(scope=scope)
            action_text = (
                "Compress, crop, or resize the screenshot before uploading."
                if "screenshot" in path
                else "Compress or split the PDF document before uploading."
            )

            # 1. Check explicit Content-Length header
            content_length_header = headers.get("content-length")
            if content_length_header is not None:
                try:
                    content_length = int(content_length_header)
                    if content_length > self.max_upload_size:
                        response = JSONResponse(
                            status_code=413,
                            content={
                                "code": "FILE_TOO_LARGE",
                                "message": (
                                    f"Request payload of {content_length:,} bytes exceeds the maximum "
                                    f"allowed size limit of 5 MiB (with 64 KiB multipart overhead)."
                                ),
                                "action": action_text,
                            },
                            headers={"Cache-Control": "no-store"},
                        )
                        await response(scope, receive, send)
                        return
                except ValueError:
                    pass

            # 2. Track streamed body chunks for missing/misleading Content-Length or chunked transfer
            bytes_received = 0
            response_started = False

            async def bounded_receive() -> Message:
                nonlocal bytes_received
                message = await receive()
                if message["type"] == "http.request":
                    body_chunk = message.get("body", b"")
                    bytes_received += len(body_chunk)
                    if bytes_received > self.max_upload_size:
                        scope["payload_too_large"] = True
                        raise StreamingPayloadTooLargeError()
                return message

            async def tracking_send(message: Message) -> None:
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                await send(message)

            try:
                await self.app(scope, bounded_receive, tracking_send)
            except StreamingPayloadTooLargeError:
                if not response_started:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "code": "FILE_TOO_LARGE",
                            "message": (
                                "Streamed request body exceeded the maximum allowed size limit of "
                                "5 MiB (with 64 KiB multipart overhead)."
                            ),
                            "action": action_text,
                        },
                        headers={"Cache-Control": "no-store"},
                    )
                    await response(scope, receive, send)
            return

        # Default path for other routes
        await self.app(scope, receive, send)
