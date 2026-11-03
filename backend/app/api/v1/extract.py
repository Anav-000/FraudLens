from typing import Optional
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import Settings, get_settings
from app.schemas.document import (
    DocumentExtractionErrorResponse,
    DocumentExtractionResponse,
)
from app.schemas.ocr import (
    ExtractionErrorResponse,
    OcrLanguage,
    ScreenshotExtractionResponse,
)
from app.services.document import (
    DocumentService,
    DocumentServiceError,
    MAX_DOCUMENT_FILE_SIZE,
)
from app.services.ocr import (
    FileTooLargeError,
    MAX_IMAGE_FILE_SIZE,
    OcrService,
    OcrServiceError,
    SUPPORTED_OCR_LANGUAGES,
)

router = APIRouter()

# 64 KiB streaming chunk size for memory-bounded upload ingestion
STREAMING_CHUNK_SIZE = 64 * 1024


ALLOWED_MULTIPART_FIELDS = {"file", "ocr_language"}
ALLOWED_DOCUMENT_MULTIPART_FIELDS = {"file"}


@router.post(
    "/extract/screenshot",
    response_model=ScreenshotExtractionResponse,
    responses={
        200: {
            "model": ScreenshotExtractionResponse,
            "description": "Extracted text ready for user review.",
        },
        413: {
            "model": ExtractionErrorResponse,
            "description": "Screenshot exceeds maximum file size limit of 5 MiB.",
        },
        422: {
            "model": ExtractionErrorResponse,
            "description": "Invalid image, unsupported format, animated file, or empty extraction.",
        },
        503: {
            "model": ExtractionErrorResponse,
            "description": "Tesseract OCR engine or requested language pack unavailable.",
        },
        504: {
            "model": ExtractionErrorResponse,
            "description": "OCR processing timed out.",
        },
        500: {
            "model": ExtractionErrorResponse,
            "description": "Unexpected extraction failure.",
        },
    },
    tags=["Extraction"],
)
async def extract_screenshot(
    request: Request,
    file: UploadFile = File(..., description="Single PNG or JPEG screenshot image file (max 5 MiB)."),
    ocr_language: str = Form(
        default="eng",
        description="OCR language pack to use ('eng' or 'hin').",
    ),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Extracts text locally from a user-uploaded screenshot image.
    Never sends the image to Google Gemini or external services.
    Enforces 5 MiB file size, 12 MP decoded limit, and Cache-Control: no-store.
    User must review and verify the extracted text before analysis.
    """
    # Verify multipart part constraints
    form = await request.form()
    unexpected_keys = [k for k in form.keys() if k not in ALLOWED_MULTIPART_FIELDS]
    if unexpected_keys:
        await file.close()
        for v in form.values():
            if isinstance(v, (UploadFile, StarletteUploadFile)) and v != file:
                await v.close()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "UNEXPECTED_MULTIPART_FIELDS",
                "message": f"Multipart payload contains unexpected field(s): {', '.join(sorted(unexpected_keys))}.",
                "action": "Submit only 'file' and optional 'ocr_language' fields.",
            },
            headers={"Cache-Control": "no-store"},
        )

    all_files = [v for _, v in form.multi_items() if isinstance(v, (UploadFile, StarletteUploadFile))]
    if len(all_files) > 1:
        for f in all_files:
            await f.close()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "MULTIPLE_FILES_REJECTED",
                "message": "Only a single screenshot image may be uploaded per request.",
                "action": "Select and upload exactly one screenshot image.",
            },
            headers={"Cache-Control": "no-store"},
        )

    # Validate ocr_language form value
    normalized_lang = ocr_language.strip().lower()
    if normalized_lang not in SUPPORTED_OCR_LANGUAGES:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "UNSUPPORTED_OCR_LANGUAGE",
                "message": f"OCR language '{ocr_language}' is not supported. Supported options: 'eng', 'hin'.",
                "action": "Select either English (eng) or Hindi (hin).",
            },
            headers={"Cache-Control": "no-store"},
        )

    # Ingest file stream with strict byte limit
    byte_chunks = []
    total_bytes_read = 0

    try:
        while True:
            chunk = await file.read(STREAMING_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes_read += len(chunk)
            if total_bytes_read > MAX_IMAGE_FILE_SIZE:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "code": "FILE_TOO_LARGE",
                        "message": "Image file exceeds the maximum allowed size of 5 MiB.",
                        "action": "Compress, crop, or resize the screenshot before uploading.",
                    },
                    headers={"Cache-Control": "no-store"},
                )
            byte_chunks.append(chunk)

        file_bytes = b"".join(byte_chunks)
    finally:
        # Guarantee closure of uploaded file handle
        await file.close()

    ocr_service = OcrService(settings.tesseract_cmd)

    try:
        result = await ocr_service.extract_text(
            file_bytes=file_bytes,
            ocr_language=normalized_lang,  # type: ignore[arg-type]
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except OcrServiceError as err:
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
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred during screenshot extraction.",
                "action": "Please try again later or paste text directly.",
            },
            headers={"Cache-Control": "no-store"},
        )


@router.post(
    "/extract/document",
    response_model=DocumentExtractionResponse,
    responses={
        200: {
            "model": DocumentExtractionResponse,
            "description": "Extracted document text ready for user review.",
        },
        413: {
            "model": DocumentExtractionErrorResponse,
            "description": "Document exceeds maximum file size limit of 5 MiB.",
        },
        422: {
            "model": DocumentExtractionErrorResponse,
            "description": "Unsupported format, invalid/encrypted PDF, page limit, or empty extraction.",
        },
        504: {
            "model": DocumentExtractionErrorResponse,
            "description": "Document processing timed out.",
        },
        500: {
            "model": DocumentExtractionErrorResponse,
            "description": "Unexpected document extraction failure.",
        },
    },
    tags=["Extraction"],
)
async def extract_document(
    request: Request,
    file: UploadFile = File(..., description="Single text-based PDF file (max 5 MiB, max 10 pages)."),
) -> Response:
    """
    Extracts embedded text locally from a user-uploaded PDF document.
    Never sends the document or extracted text to Google Gemini or external services.
    Enforces 5 MiB file size, 10-page document limit, 10,000-character limit,
    and Cache-Control: no-store on all responses.
    Untrusted PDF parsing runs in an isolated, separately terminable worker process.
    User must review and confirm the extracted text before downstream analysis.
    """
    # Verify multipart part constraints
    form = await request.form()
    unexpected_keys = [k for k in form.keys() if k not in ALLOWED_DOCUMENT_MULTIPART_FIELDS]
    if unexpected_keys:
        await file.close()
        for v in form.values():
            if isinstance(v, (UploadFile, StarletteUploadFile)) and v != file:
                await v.close()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "UNEXPECTED_MULTIPART_FIELDS",
                "message": f"Multipart payload contains unexpected field(s): {', '.join(sorted(unexpected_keys))}.",
                "action": "Submit only the 'file' field for document extraction.",
            },
            headers={"Cache-Control": "no-store"},
        )

    all_files = [v for _, v in form.multi_items() if isinstance(v, (UploadFile, StarletteUploadFile))]
    if len(all_files) > 1:
        for f in all_files:
            await f.close()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "MULTIPLE_FILES_REJECTED",
                "message": "Only a single PDF document may be uploaded per request.",
                "action": "Select and upload exactly one PDF file.",
            },
            headers={"Cache-Control": "no-store"},
        )

    # Ingest file stream with strict byte limit
    byte_chunks = []
    total_bytes_read = 0

    try:
        while True:
            chunk = await file.read(STREAMING_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes_read += len(chunk)
            if total_bytes_read > MAX_DOCUMENT_FILE_SIZE:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "code": "FILE_TOO_LARGE",
                        "message": "Document file exceeds the maximum allowed size of 5 MiB.",
                        "action": "Compress or split the PDF document before uploading.",
                    },
                    headers={"Cache-Control": "no-store"},
                )
            byte_chunks.append(chunk)

        file_bytes = b"".join(byte_chunks)
    finally:
        # Guarantee closure of uploaded file handle
        await file.close()

    document_service = DocumentService()

    try:
        result = await document_service.extract_text(file_bytes=file_bytes)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except DocumentServiceError as err:
        error_content = {
            "code": err.code,
            "message": err.message,
            "action": err.action,
        }
        if err.page_count is not None:
            error_content["page_count"] = err.page_count
        if err.char_count is not None:
            error_content["char_count"] = err.char_count
        if err.reason:
            error_content["reason"] = err.reason

        return JSONResponse(
            status_code=err.http_status,
            content=error_content,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred during document extraction.",
                "action": "Please try again later or paste text directly.",
            },
            headers={"Cache-Control": "no-store"},
        )
