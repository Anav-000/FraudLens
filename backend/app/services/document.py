"""
Document extraction service for text-based PDF processing.
Enforces:
- 5 MiB file size limits.
- 10-page document length limits.
- 10,000-character extracted text limits.
- Isolated, separately terminable worker process execution (pypdf parsing).
- Bounded concurrency with asyncio.Semaphore(3).
- Strict 20-second execution timeout with process kill and reaping.
- Automatic temporary file cleanup on all execution paths.
- Cache-Control: no-store and safe error response mapping.
- Purely local processing: zero external network transmission to AI providers.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.document import DocumentExtractionResponse, DocumentPageInfo

# Operational Constraints
MAX_DOCUMENT_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB
MAX_DOCUMENT_PAGES = 10
MAX_EXTRACTED_CHARACTERS = 10_000
MAX_WORKER_RESULT_BYTES = 1024 * 1024  # 1 MiB worker JSON result ceiling
DOCUMENT_TIMEOUT_SECONDS = 20.0
PDF_MAGIC_BYTES = b"%PDF-"

# Bounded concurrency semaphore for document extraction.
# Note on Combined Concurrency:
# _document_semaphore (3) operates independently from OCR's _ocr_semaphore (3),
# permitting up to 3 concurrent OCR workers plus 3 concurrent PDF extraction workers
# (up to 6 concurrent extraction subprocesses total across both modalities), rather than
# sharing a single combined semaphore of 3.
_document_semaphore = asyncio.Semaphore(3)


class DocumentServiceError(Exception):
    """Base exception for all document extraction errors."""
    def __init__(
        self,
        code: str,
        message: str,
        action: str = "Please verify your document and try again.",
        http_status: int = 422,
        page_count: Optional[int] = None,
        char_count: Optional[int] = None,
        reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.http_status = http_status
        self.page_count = page_count
        self.char_count = char_count
        self.reason = reason


class UnsupportedDocumentFormatError(DocumentServiceError):
    def __init__(self, message: str = "Only PDF documents (.pdf) are supported."):
        super().__init__(
            code="UNSUPPORTED_DOCUMENT_FORMAT",
            message=message,
            action="Please select a valid text-based PDF file.",
            http_status=422,
        )


class DocumentFileTooLargeError(DocumentServiceError):
    def __init__(self, message: str = "Document file exceeds the maximum allowed size of 5 MiB."):
        super().__init__(
            code="FILE_TOO_LARGE",
            message=message,
            action="Compress or split the PDF document before uploading.",
            http_status=413,
        )


class InvalidPdfError(DocumentServiceError):
    def __init__(self, message: str = "Could not parse PDF. The file may be corrupt, damaged, or not a valid PDF."):
        super().__init__(
            code="INVALID_PDF",
            message=message,
            action="Ensure the file is a valid, undamaged PDF document.",
            http_status=422,
        )


class EncryptedPdfError(DocumentServiceError):
    def __init__(self, message: str = "Password-protected or encrypted PDFs are not supported."):
        super().__init__(
            code="ENCRYPTED_PDF_REJECTED",
            message=message,
            action="Please upload an unencrypted text-based PDF.",
            http_status=422,
        )


class PageLimitExceededError(DocumentServiceError):
    def __init__(self, page_count: int):
        super().__init__(
            code="PAGE_LIMIT_EXCEEDED",
            message=f"Document contains {page_count} pages, which exceeds the maximum limit of {MAX_DOCUMENT_PAGES} pages.",
            action=f"Upload a PDF with {MAX_DOCUMENT_PAGES} or fewer pages.",
            http_status=422,
            page_count=page_count,
        )


class EmptyDocumentExtractionError(DocumentServiceError):
    def __init__(
        self,
        message: str = (
            "No usable text could be extracted from this PDF. Scanned PDFs, image-only "
            "documents, and non-standard encodings are not supported."
        ),
    ):
        super().__init__(
            code="EMPTY_DOCUMENT_EXTRACTION",
            message=message,
            action="Ensure the PDF contains embedded text rather than scanned images, or use Screenshot Text Extraction.",
            http_status=422,
        )


class DocumentTextTooLongError(DocumentServiceError):
    def __init__(self, char_count: int):
        super().__init__(
            code="TEXT_TOO_LONG",
            message=f"Extracted text exceeds the maximum limit of {MAX_EXTRACTED_CHARACTERS:,} characters ({char_count:,} characters extracted).",
            action="Upload a shorter document excerpt or paste specific suspicious text directly.",
            http_status=422,
            char_count=char_count,
        )


class DocumentTimeoutError(DocumentServiceError):
    def __init__(self):
        super().__init__(
            code="DOCUMENT_TIMEOUT",
            message=f"Document text extraction timed out after {int(DOCUMENT_TIMEOUT_SECONDS)} seconds.",
            action="Try uploading a shorter or simpler PDF document, or paste the text directly.",
            http_status=504,
        )


class DocumentExecutionError(DocumentServiceError):
    def __init__(
        self,
        message: str = "An error occurred while executing document text extraction.",
        reason: Optional[str] = "WORKER_FAILED",
    ):
        super().__init__(
            code="DOCUMENT_EXTRACTION_FAILED",
            message=message,
            action="Try again with a simpler text PDF or copy and paste the text directly.",
            http_status=500,
            reason=reason,
        )


class _SyncDocumentRunner:
    """
    Coordinates execution of the isolated PDF worker subprocess in a worker thread.
    Guarantees:
    - cancel() never blocks the asyncio event loop (mutex does not span Popen; no synchronous waits).
    - cancel() before, during, or after process creation terminates and reaps child processes.
    - Process reaping (proc.wait()) is performed by the worker thread pool, not the event loop.
    - No orphan process survives cancellation or timeout.
    """
    def __init__(
        self,
        input_pdf_path: str,
        output_json_path: str,
        timeout: float,
    ):
        self.input_pdf_path = input_pdf_path
        self.output_json_path = output_json_path
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._done = threading.Event()

    def run(self) -> int:
        if self._cancel_event.is_set():
            self._done.set()
            raise asyncio.CancelledError("Document worker cancelled prior to process creation.")

        try:
            worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "pdf_worker.py"))
            # Execute worker as a separate Python process with discarded stdout/stderr to avoid unbounded buffers
            proc = subprocess.Popen(
                [
                    sys.executable,
                    worker_script,
                    self.input_pdf_path,
                    self.output_json_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._done.set()
            raise

        with self._lock:
            self.proc = proc

        if self._cancel_event.is_set():
            self._terminate_and_reap()
            self._done.set()
            raise asyncio.CancelledError("Document worker cancelled during process creation.")

        try:
            proc.wait(timeout=self.timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            self._terminate_and_reap()
            raise
        except Exception:
            self._terminate_and_reap()
            raise
        finally:
            self._terminate_and_reap()
            self._done.set()

    def cancel(self) -> None:
        """
        Signals cancellation and terminates child process nonblockingly.
        Does not block on synchronous wait().
        Reaping is completed by the worker thread.
        """
        self._cancel_event.set()
        with self._lock:
            p = self.proc
        if p is not None:
            try:
                if p.poll() is None:
                    p.kill()
            except OSError:
                pass

    def _terminate_and_reap(self) -> None:
        """Executed within worker thread pool to terminate and reap child process."""
        with self._lock:
            p = self.proc
        if p is not None:
            try:
                if p.poll() is None:
                    p.kill()
                p.wait()
            except OSError:
                pass


class DocumentService:
    """
    Service adapter for local text-based PDF document extraction.
    Enforces strict file constraints, isolated worker process execution,
    bounded timeouts, and guaranteed resource cleanup.
    Never makes network requests or contacts Google Gemini.
    """
    def __init__(self):
        pass

    def validate_file_bytes(self, file_bytes: bytes) -> None:
        """
        Validates raw PDF bytes before saving to disk.
        """
        if len(file_bytes) > MAX_DOCUMENT_FILE_SIZE:
            raise DocumentFileTooLargeError()

        if len(file_bytes) == 0:
            raise InvalidPdfError("Uploaded file is empty.")

        if not file_bytes.startswith(PDF_MAGIC_BYTES):
            raise UnsupportedDocumentFormatError(
                "File does not start with a valid PDF header (%PDF-). Only text-based PDF documents are supported."
            )

    async def extract_text(self, file_bytes: bytes) -> DocumentExtractionResponse:
        """
        Coordinates full document extraction:
        1. Validates byte limits and PDF magic header.
        2. Writes to temporary input file.
        3. Executes isolated worker subprocess with bounded concurrency and timeout.
        4. Reaps worker and reads structured output.
        5. Unlinks temporary files unconditionally.
        """
        self.validate_file_bytes(file_bytes)

        temp_pdf_path = None
        temp_output_path = None

        try:
            # Create temporary input PDF
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_pdf:
                f_pdf.write(file_bytes)
                temp_pdf_path = f_pdf.name

            # Create temporary output JSON
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f_out:
                temp_output_path = f_out.name

            # Execute worker with bounded concurrency
            async with _document_semaphore:
                runner = _SyncDocumentRunner(
                    temp_pdf_path,
                    temp_output_path,
                    DOCUMENT_TIMEOUT_SECONDS,
                )
                worker_task = asyncio.create_task(
                    asyncio.to_thread(runner.run)
                )

                try:
                    returncode = await asyncio.wait_for(
                        asyncio.shield(worker_task),
                        timeout=DOCUMENT_TIMEOUT_SECONDS + 1.0,
                    )
                except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                    runner.cancel()
                    while not worker_task.done():
                        try:
                            await asyncio.shield(worker_task)
                        except (asyncio.CancelledError, Exception):
                            pass
                    await asyncio.to_thread(runner._terminate_and_reap)
                    raise DocumentTimeoutError()
                except asyncio.CancelledError:
                    runner.cancel()
                    while not worker_task.done():
                        try:
                            await asyncio.shield(worker_task)
                        except (asyncio.CancelledError, Exception):
                            pass
                    await asyncio.to_thread(runner._terminate_and_reap)
                    raise
                except Exception as exc:
                    runner.cancel()
                    while not worker_task.done():
                        try:
                            await asyncio.shield(worker_task)
                        except (asyncio.CancelledError, Exception):
                            pass
                    await asyncio.to_thread(runner._terminate_and_reap)
                    if isinstance(exc, DocumentServiceError):
                        raise
                    raise DocumentExecutionError(
                        "PDF extraction worker execution failed.",
                        reason="WORKER_EXECUTION_ERROR",
                    ) from exc

            # Read and parse worker output with strict byte limits
            if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) == 0:
                raise DocumentExecutionError(
                    "PDF extraction worker exited without generating output.",
                    reason="WORKER_EMPTY_OUTPUT",
                )

            output_file_size = os.path.getsize(temp_output_path)
            if output_file_size > MAX_WORKER_RESULT_BYTES:
                raise DocumentExecutionError(
                    "Worker extraction result exceeded the maximum allowed size limit (1 MiB).",
                    reason="WORKER_RESULT_TOO_LARGE",
                )

            try:
                with open(temp_output_path, "r", encoding="utf-8") as f:
                    raw_content = f.read(MAX_WORKER_RESULT_BYTES + 1)
                    if len(raw_content) > MAX_WORKER_RESULT_BYTES:
                        raise DocumentExecutionError(
                            "Worker extraction result exceeded the maximum allowed size limit (1 MiB).",
                            reason="WORKER_RESULT_TOO_LARGE",
                        )
                    worker_result = json.loads(raw_content)
            except DocumentExecutionError:
                raise
            except Exception as exc:
                raise DocumentExecutionError(
                    "Could not decode worker output.",
                    reason="WORKER_OUTPUT_PARSE_ERROR",
                ) from exc

            if worker_result.get("status") == "error":
                code = worker_result.get("code")
                msg = worker_result.get("message", "PDF extraction failed.")
                action = worker_result.get("action", "Please verify your document and try again.")
                page_count = worker_result.get("page_count")
                char_count = worker_result.get("char_count")

                if code == "ENCRYPTED_PDF_REJECTED":
                    raise EncryptedPdfError(msg)
                elif code == "PAGE_LIMIT_EXCEEDED":
                    raise PageLimitExceededError(page_count=page_count or MAX_DOCUMENT_PAGES + 1)
                elif code == "TEXT_TOO_LONG":
                    raise DocumentTextTooLongError(char_count=char_count or MAX_EXTRACTED_CHARACTERS + 1)
                elif code == "EMPTY_DOCUMENT_EXTRACTION":
                    raise EmptyDocumentExtractionError(msg)
                elif code == "INVALID_PDF":
                    raise InvalidPdfError(msg)
                else:
                    raise DocumentExecutionError(msg, reason=code)

            # Map to response schema
            pages = [
                DocumentPageInfo(
                    page_number=p["page_number"],
                    has_text=p["has_text"],
                    char_count=p["char_count"],
                )
                for p in worker_result.get("pages", [])
            ]

            return DocumentExtractionResponse(
                combined_text=worker_result["combined_text"],
                page_count=worker_result["page_count"],
                char_count=worker_result["char_count"],
                extraction_method="embedded_text",
                empty_pages=worker_result.get("empty_pages", []),
                warning=worker_result.get("warning"),
                pages=pages,
                review_required=True,
                notice=worker_result.get(
                    "notice",
                    "Analysis evaluates the submitted reviewed text only. Findings concern textual content, "
                    "not document authenticity, signatures, visual tampering, sender identity, or URL reputation.",
                ),
                limitation=worker_result.get(
                    "limitation",
                    "Extraction evaluates embedded text only. Images, signatures, layout, and image-only "
                    "text are not evaluated.",
                ),
            )

        finally:
            # Unconditional cleanup of all temporary files
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except OSError:
                    pass
            if temp_output_path and os.path.exists(temp_output_path):
                try:
                    os.unlink(temp_output_path)
                except OSError:
                    pass
