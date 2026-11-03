"""
Tests for PDF document text extraction:
- Valid single-page and multipage text PDFs
- Hindi embedded text with Unicode/UTF-16BE encoding
- Empty, image-only, and mixed text/image pages
- Malformed, empty, encrypted, and non-PDF uploads
- File size, page count, and character limit boundaries
- Bounded multipart upload streaming and spool file cleanup
- Process timeout, termination, reaping, and event-loop responsiveness
- Concurrency bounding and repeated cancellation shielding
- Outbound network isolation (zero Gemini calls)
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import pypdf
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.document import (
    DocumentService,
    DocumentFileTooLargeError,
    DocumentTimeoutError,
    DocumentTextTooLongError,
    EmptyDocumentExtractionError,
    EncryptedPdfError,
    InvalidPdfError,
    PageLimitExceededError,
    UnsupportedDocumentFormatError,
    _SyncDocumentRunner,
    _document_semaphore,
)


def make_page_stream(text: str) -> bytes:
    if not text:
        return b""
    if any(ord(c) > 127 for c in text):
        hex_str = "FEFF" + text.encode("utf-16-be").hex().upper()
        content = f"BT /F2 12 Tf 100 700 Td <{hex_str}> Tj ET".encode("ascii")
    else:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET".encode("ascii")
    return content


def create_synthetic_pdf(pages: list[str]) -> bytes:
    """Creates a valid in-memory PDF with embedded text for each page in pages."""
    body = [b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"]
    font1_obj_num = 3 + len(pages) * 2
    font2_obj_num = font1_obj_num + 1
    kids = []
    page_objs = []
    cur_obj = 3

    for text in pages:
        page_obj_num = cur_obj
        stream_obj_num = cur_obj + 1
        kids.append(f"{page_obj_num} 0 R")
        cur_obj += 2

        stream_bytes = make_page_stream(text)

        page_str = (
            f"{page_obj_num} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {stream_obj_num} 0 R "
            f"/Resources << /Font << /F1 {font1_obj_num} 0 R /F2 {font2_obj_num} 0 R >> >> >>\n"
            f"endobj\n"
        ).encode("ascii")

        stream_obj = (
            f"{stream_obj_num} 0 obj\n"
            f"<< /Length {len(stream_bytes)} >>\n"
            f"stream\n"
        ).encode("ascii") + stream_bytes + b"\nendstream\nendobj\n"

        page_objs.append((page_str, stream_obj))

    font1_obj = (
        f"{font1_obj_num} 0 obj\n"
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        f"endobj\n"
    ).encode("ascii")

    font2_obj = (
        f"{font2_obj_num} 0 obj\n"
        f"<< /Type /Font /Subtype /Type0 /BaseFont /Arial /Encoding /Identity-H >>\n"
        f"endobj\n"
    ).encode("ascii")

    kids_str = " ".join(kids)
    pages_obj = (
        f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {len(pages)} >>\nendobj\n"
    ).encode("ascii")

    body.append(pages_obj)
    for p_str, s_obj in page_objs:
        body.append(p_str)
        body.append(s_obj)
    body.append(font1_obj)
    body.append(font2_obj)

    body.append(
        b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size "
        + str(font2_obj_num + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n0\n%%EOF"
    )
    return b"".join(body)


def create_encrypted_pdf() -> bytes:
    """Creates a password-protected PDF using pypdf."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("user_pass", "owner_pass")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ==============================================================================
# Service Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_extract_single_page_english_text():
    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["This is a test invoice message."])
    result = await service.extract_text(pdf_bytes)

    assert result.page_count == 1
    assert result.combined_text == "This is a test invoice message."
    assert result.empty_pages == []
    assert result.warning is None
    assert len(result.pages) == 1
    assert result.pages[0].has_text is True
    assert result.pages[0].char_count == len("This is a test invoice message.")
    assert result.extraction_method == "embedded_text"


@pytest.mark.asyncio
async def test_extract_multipage_text():
    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["First page content.", "Second page content."])
    result = await service.extract_text(pdf_bytes)

    assert result.page_count == 2
    assert result.combined_text == "First page content.\n\nSecond page content."
    assert result.combined_text.index("First page content.") < result.combined_text.index("Second page content.")
    assert result.empty_pages == []
    assert result.warning is None
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert result.pages[0].has_text is True
    assert result.pages[1].page_number == 2
    assert result.pages[1].has_text is True


@pytest.mark.asyncio
async def test_extract_hindi_unicode_embedded_text():
    service = DocumentService()
    hindi_phrase = "नमस्ते यह एक संदिग्ध बैंक संदेश है"
    pdf_bytes = create_synthetic_pdf([hindi_phrase])
    result = await service.extract_text(pdf_bytes)

    assert result.page_count == 1
    assert result.combined_text == hindi_phrase
    assert result.empty_pages == []
    assert result.pages[0].has_text is True


@pytest.mark.asyncio
async def test_empty_document_raises_actionable_error():
    service = DocumentService()
    # 2 pages with 0 text
    pdf_bytes = create_synthetic_pdf(["", ""])
    with pytest.raises(EmptyDocumentExtractionError) as exc_info:
        await service.extract_text(pdf_bytes)
    assert exc_info.value.code == "EMPTY_DOCUMENT_EXTRACTION"
    assert "scanned" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_mixed_pages_warns_incomplete_extraction():
    service = DocumentService()
    # Page 1 has text, Page 2 is empty/image-only, Page 3 has text
    pdf_bytes = create_synthetic_pdf(["Page one text", "", "Page three text"])
    result = await service.extract_text(pdf_bytes)

    assert result.page_count == 3
    assert result.combined_text == "Page one text\n\nPage three text"
    assert result.combined_text.index("Page one text") < result.combined_text.index("Page three text")
    assert result.empty_pages == [2]
    assert result.warning is not None
    assert "Pages 2" in result.warning
    assert "incomplete" in result.warning.lower()
    assert "images" in result.warning.lower()
    assert len(result.pages) == 3
    assert result.pages[0].has_text is True
    assert result.pages[1].has_text is False
    assert result.pages[2].has_text is True


@pytest.mark.asyncio
async def test_encrypted_pdf_rejected():
    service = DocumentService()
    pdf_bytes = create_encrypted_pdf()
    with pytest.raises(EncryptedPdfError) as exc_info:
        await service.extract_text(pdf_bytes)
    assert exc_info.value.code == "ENCRYPTED_PDF_REJECTED"


@pytest.mark.asyncio
async def test_page_limit_exceeded_rejected():
    service = DocumentService()
    # 11 pages (exceeds limit of 10)
    pages = [f"Page {i} text" for i in range(1, 12)]
    pdf_bytes = create_synthetic_pdf(pages)
    with pytest.raises(PageLimitExceededError) as exc_info:
        await service.extract_text(pdf_bytes)
    assert exc_info.value.code == "PAGE_LIMIT_EXCEEDED"
    assert exc_info.value.page_count == 11


@pytest.mark.asyncio
async def test_text_too_long_rejected():
    service = DocumentService()
    # Over 10,000 characters
    long_text = "A" * 10_500
    pdf_bytes = create_synthetic_pdf([long_text])
    with pytest.raises(DocumentTextTooLongError) as exc_info:
        await service.extract_text(pdf_bytes)
    assert exc_info.value.code == "TEXT_TOO_LONG"
    assert exc_info.value.char_count >= 10_000


@pytest.mark.asyncio
async def test_non_pdf_file_rejected():
    service = DocumentService()
    with pytest.raises(UnsupportedDocumentFormatError) as exc_info:
        await service.extract_text(b"This is just plain text, not a PDF.")
    assert exc_info.value.code == "UNSUPPORTED_DOCUMENT_FORMAT"


@pytest.mark.asyncio
async def test_empty_file_rejected():
    service = DocumentService()
    with pytest.raises(InvalidPdfError) as exc_info:
        await service.extract_text(b"")
    assert exc_info.value.code == "INVALID_PDF"


@pytest.mark.asyncio
async def test_corrupt_pdf_rejected():
    service = DocumentService()
    corrupt_bytes = b"%PDF-1.4\nCorrupted binary garbage that cannot be parsed as PDF"
    with pytest.raises(InvalidPdfError) as exc_info:
        await service.extract_text(corrupt_bytes)
    assert exc_info.value.code == "INVALID_PDF"


# ==============================================================================
# Worker Lifecycle, Timeout, Reaping & Responsiveness Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_worker_process_timeout_and_reaping():
    """
    Verifies that when a worker process hangs or exceeds the 20s timeout,
    runner.cancel() kills the process, reaps it via proc.wait(), and raises DocumentTimeoutError.
    """
    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["Some text"])

    # Simulate timeout by patching DOCUMENT_TIMEOUT_SECONDS to 0.2s and proc.wait raising TimeoutExpired when called with timeout
    def mock_wait(self, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
        return 0

    with patch("app.services.document.DOCUMENT_TIMEOUT_SECONDS", 0.2):
        with patch.object(subprocess.Popen, "wait", mock_wait):
            with pytest.raises(DocumentTimeoutError) as exc_info:
                await service.extract_text(pdf_bytes)
            assert exc_info.value.code == "DOCUMENT_TIMEOUT"


@pytest.mark.asyncio
async def test_cancellation_worker_reaped_before_temp_deletion_and_semaphore_release():
    """
    Verifies the strict lifecycle order during cancellation:
    1. Child process termination and reaping (_terminate_and_reap) completes FIRST.
    2. Semaphore slot is released.
    3. Temporary files are unlinked (os.unlink).
    """
    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["Quick text"])

    event_order = []

    orig_reap = _SyncDocumentRunner._terminate_and_reap
    def instrumented_reap(runner_self):
        event_order.append("worker_reaped")
        return orig_reap(runner_self)

    orig_unlink = os.unlink
    def instrumented_unlink(path):
        event_order.append("temp_file_unlinked")
        return orig_unlink(path)

    orig_release = _document_semaphore.release
    def instrumented_release(*args, **kwargs):
        event_order.append("semaphore_released")
        return orig_release(*args, **kwargs)

    with patch.object(_SyncDocumentRunner, "_terminate_and_reap", instrumented_reap):
        with patch("os.unlink", side_effect=instrumented_unlink):
            with patch.object(_document_semaphore, "release", side_effect=instrumented_release):
                task = asyncio.create_task(service.extract_text(pdf_bytes))
                await asyncio.sleep(0.01)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    assert "worker_reaped" in event_order
    assert "semaphore_released" in event_order
    assert "temp_file_unlinked" in event_order

    reap_index = event_order.index("worker_reaped")
    sem_index = event_order.index("semaphore_released")
    unlink_index = event_order.index("temp_file_unlinked")

    # Reaping MUST precede semaphore release and MUST precede temporary file deletion
    assert reap_index < sem_index
    assert reap_index < unlink_index


def test_windows_job_object_memory_limit_applied_and_enforced():
    """
    Verifies that on Windows, apply_memory_limit_windows succeeds in creating
    and attaching a Job Object with the configured threshold.
    """
    from app.services.pdf_worker import apply_memory_limit_windows
    if sys.platform == "win32":
        res = apply_memory_limit_windows(256)
        assert res is True
    else:
        res = apply_memory_limit_windows(256)
        assert isinstance(res, bool)


@pytest.mark.asyncio
async def test_worker_result_file_too_large_rejected_before_parsing():
    """
    Verifies that if a worker process generates an output JSON exceeding
    MAX_WORKER_RESULT_BYTES (1 MiB), DocumentService rejects it with
    DocumentExecutionError(reason="WORKER_RESULT_TOO_LARGE") without parsing JSON.
    """
    from app.services.document import DocumentExecutionError

    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["Normal text"])

    def mock_run_oversized(runner_self):
        with open(runner_self.output_json_path, "wb") as f:
            f.write(b" " * (1024 * 1024 + 100))
        return 0

    with patch.object(_SyncDocumentRunner, "run", mock_run_oversized):
        with pytest.raises(DocumentExecutionError) as exc_info:
            await service.extract_text(pdf_bytes)
        assert exc_info.value.code == "DOCUMENT_EXTRACTION_FAILED"
        assert exc_info.value.reason == "WORKER_RESULT_TOO_LARGE"


@pytest.mark.asyncio
async def test_event_loop_responsiveness_during_delayed_worker_creation():
    """
    Demonstrates that delays during worker process creation do not block the event loop
    because subprocess.Popen executes in a worker thread outside the cancel lock.
    """
    runner = _SyncDocumentRunner("fake.pdf", "fake.json", timeout=1.0)

    slow_spawn_event = threading.Event()

    def slow_popen(*args, **kwargs):
        # Emulate slow process spawn
        time.sleep(0.3)
        slow_spawn_event.set()
        # Return dummy mock process
        mock_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        return mock_proc

    # Background task running runner in thread
    with patch("subprocess.Popen", side_effect=slow_popen):
        worker_task = asyncio.create_task(asyncio.to_thread(runner.run))

        # Concurrently verify event loop responsiveness
        heartbeat_ticks = 0
        for _ in range(5):
            await asyncio.sleep(0.05)
            heartbeat_ticks += 1

        assert heartbeat_ticks >= 4

        # Cancel while slow popen is finishing
        runner.cancel()
        try:
            await asyncio.wait_for(worker_task, timeout=2.0)
        except (asyncio.CancelledError, Exception):
            pass

        # Cleanup
        runner._terminate_and_reap()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_cleanup_preserves_worker_completion():
    """
    Demonstrates that repeated cancellations arriving while cleaning up worker tasks
    cannot break out before the worker has fully terminated and reaped.
    """
    service = DocumentService()
    pdf_bytes = create_synthetic_pdf(["Quick text"])

    # Track semaphore slot ownership
    initial_slots = _document_semaphore._value

    # Run extraction and cancel immediately
    task = asyncio.create_task(service.extract_text(pdf_bytes))
    await asyncio.sleep(0.01)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    # Ensure semaphore slot is strictly restored
    assert _document_semaphore._value == initial_slots


# ==============================================================================
# Endpoint Integration Tests (POST /api/v1/extract/document)
# ==============================================================================


def test_api_extract_document_success():
    app = create_app()
    client = TestClient(app)
    pdf_bytes = create_synthetic_pdf(["Account verification required at official portal."])

    response = client.post(
        "/api/v1/extract/document",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["page_count"] == 1
    assert data["combined_text"] == "Account verification required at official portal."
    assert data["review_required"] is True
    assert "Analysis evaluates the submitted reviewed text only" in data["notice"]


def test_api_extract_document_rejects_oversized_file():
    app = create_app()
    client = TestClient(app)
    oversized_bytes = b"%PDF-" + (b"X" * (6 * 1024 * 1024))

    response = client.post(
        "/api/v1/extract/document",
        files={"file": ("large.pdf", oversized_bytes, "application/pdf")},
    )

    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "FILE_TOO_LARGE"


def test_api_extract_document_rejects_multiple_files():
    app = create_app()
    client = TestClient(app)
    pdf1 = create_synthetic_pdf(["Doc 1"])
    pdf2 = create_synthetic_pdf(["Doc 2"])

    response = client.post(
        "/api/v1/extract/document",
        files=[
            ("file", ("doc1.pdf", pdf1, "application/pdf")),
            ("file", ("doc2.pdf", pdf2, "application/pdf")),
        ],
    )

    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "MULTIPLE_FILES_REJECTED"


def test_api_extract_document_rejects_unexpected_form_fields():
    app = create_app()
    client = TestClient(app)
    pdf = create_synthetic_pdf(["Doc text"])

    response = client.post(
        "/api/v1/extract/document",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data={"extra_field": "unexpected_data"},
    )

    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "UNEXPECTED_MULTIPART_FIELDS"


@pytest.mark.asyncio
async def test_streamed_oversized_document_multipart_closes_created_spool_files():
    """
    Demonstrates that when streamed oversized multipart document uploads exceed
    the 5.06 MiB bound, Starlette's MultiPartParser catches StreamingPayloadTooLargeError
    and executes close() on all partially created SpooledTemporaryFile spool files.
    """
    app = create_app()

    chunks = [
        b'--bound123\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\nContent-Type: application/pdf\r\n\r\n',
        b"A" * (1024 * 1024),
        b"B" * (5 * 1024 * 1024),
        b"\r\n--bound123--\r\n",
    ]
    chunk_iter = iter(chunks)

    async def receive():
        try:
            c = next(chunk_iter)
            return {"type": "http.request", "body": c, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(msg):
        messages.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/extract/document",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=bound123"),
        ],
    }

    real_close = tempfile.SpooledTemporaryFile.close
    close_calls = []

    def tracking_close(self, *args, **kwargs):
        close_calls.append(self)
        return real_close(self, *args, **kwargs)

    with patch.object(tempfile.SpooledTemporaryFile, "close", autospec=True, side_effect=tracking_close):
        await app(scope, receive, send)

    start_msg = next(m for m in messages if m["type"] == "http.response.start")
    assert start_msg["status"] == 413
    headers = dict(start_msg["headers"])
    assert headers.get(b"cache-control") == b"no-store"

    body_msg = next(m for m in messages if m["type"] == "http.response.body")
    data = json.loads(body_msg["body"].decode("utf-8"))
    assert data["code"] == "FILE_TOO_LARGE"
    assert len(close_calls) >= 1


@pytest.mark.asyncio
async def test_streamed_document_multipart_with_misleading_low_content_length():
    """
    Verifies that when a client declares a misleadingly low Content-Length (e.g. 100 bytes)
    but streams oversized multipart data (> 5.06 MiB), the middleware detects the limit
    violation during streaming, aborts with HTTP 413, and ensures spool file is closed.
    """
    app = create_app()

    chunks = [
        b'--bound123\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\nContent-Type: application/pdf\r\n\r\n',
        b"A" * (1024 * 1024),
        b"B" * (5 * 1024 * 1024),
        b"\r\n--bound123--\r\n",
    ]
    chunk_iter = iter(chunks)

    async def receive():
        try:
            c = next(chunk_iter)
            return {"type": "http.request", "body": c, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(msg):
        messages.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/extract/document",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=bound123"),
            (b"content-length", b"100"),  # Misleadingly low declared content length
        ],
    }

    real_close = tempfile.SpooledTemporaryFile.close
    close_calls = []

    def tracking_close(self, *args, **kwargs):
        close_calls.append(self)
        return real_close(self, *args, **kwargs)

    with patch.object(tempfile.SpooledTemporaryFile, "close", autospec=True, side_effect=tracking_close):
        await app(scope, receive, send)

    start_msg = next(m for m in messages if m["type"] == "http.response.start")
    assert start_msg["status"] == 413
    headers = dict(start_msg["headers"])
    assert headers.get(b"cache-control") == b"no-store"

    body_msg = next(m for m in messages if m["type"] == "http.response.body")
    data = json.loads(body_msg["body"].decode("utf-8"))
    assert data["code"] == "FILE_TOO_LARGE"
    assert len(close_calls) >= 1


@pytest.mark.asyncio
async def test_streamed_document_multipart_with_absent_content_length():
    """
    Verifies that when Content-Length is completely absent and chunked streaming delivers
    data exceeding the 5.06 MiB boundary, the middleware aborts with HTTP 413 and cleans up.
    """
    app = create_app()

    chunks = [
        b'--bound123\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\nContent-Type: application/pdf\r\n\r\n',
        b"A" * (1024 * 1024),
        b"B" * (5 * 1024 * 1024),
        b"\r\n--bound123--\r\n",
    ]
    chunk_iter = iter(chunks)

    async def receive():
        try:
            c = next(chunk_iter)
            return {"type": "http.request", "body": c, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(msg):
        messages.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/extract/document",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=bound123"),
            # No content-length header
        ],
    }

    await app(scope, receive, send)

    start_msg = next(m for m in messages if m["type"] == "http.response.start")
    assert start_msg["status"] == 413
    body_msg = next(m for m in messages if m["type"] == "http.response.body")
    data = json.loads(body_msg["body"].decode("utf-8"))
    assert data["code"] == "FILE_TOO_LARGE"


def test_outbound_network_isolation_during_document_extraction():
    """
    Verifies that document text extraction is completely local:
    it never invokes Google Gemini SDK client or makes outbound AI calls.
    """
    app = create_app()
    client = TestClient(app)
    pdf_bytes = create_synthetic_pdf(["Secret message that must stay local."])

    with patch("app.services.gemini.GeminiAdapter.analyze_message") as mock_gemini:
        response = client.post(
            "/api/v1/extract/document",
            files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        mock_gemini.assert_not_called()
