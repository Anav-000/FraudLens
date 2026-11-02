import io
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.core.config import Settings, get_settings
from app.schemas.ocr import ScreenshotExtractionResponse
from app.services.ocr import (
    AnimatedImageError,
    EmptyExtractionError,
    ImageTooLargeError,
    InvalidImageError,
    OcrLanguageNotInstalledError,
    OcrTimeoutError,
    OcrUnavailableError,
    TextTooLongError,
)


@pytest.fixture
def client():
    isolated_settings = Settings(
        ai_provider="none",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: isolated_settings
    return TestClient(app)


def create_test_image_bytes(format="PNG", size=(50, 50), color=(0, 128, 255)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    return buf.getvalue()


def test_extract_screenshot_success_png(client):
    png_bytes = create_test_image_bytes("PNG")
    mock_response = ScreenshotExtractionResponse(
        extracted_text="You have won a lottery of $1,000,000. Send $100 processing fee to claim.",
        ocr_language="eng",
        character_count=73,
        review_required=True,
        notice="Please review and edit the extracted text.",
    )

    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_response

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", png_bytes, "image/png")},
            data={"ocr_language": "eng"},
        )

        assert response.status_code == 200
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["extracted_text"] == mock_response.extracted_text
        assert data["ocr_language"] == "eng"
        assert data["character_count"] == 73
        assert data["review_required"] is True
        assert "review" in data["notice"].lower()


def test_extract_screenshot_success_jpeg(client):
    jpeg_bytes = create_test_image_bytes("JPEG")
    mock_response = ScreenshotExtractionResponse(
        extracted_text="Immediate payment required for unpaid toll invoice.",
        ocr_language="eng",
        character_count=51,
        review_required=True,
        notice="Please review and edit the extracted text.",
    )

    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_response

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.jpg", jpeg_bytes, "image/jpeg")},
            data={"ocr_language": "eng"},
        )

        assert response.status_code == 200
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["extracted_text"] == mock_response.extracted_text


def test_extract_screenshot_rejects_unsupported_ocr_language(client):
    png_bytes = create_test_image_bytes("PNG")
    response = client.post(
        "/api/v1/extract/screenshot",
        files={"file": ("screenshot.png", png_bytes, "image/png")},
        data={"ocr_language": "fra"},
    )
    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "UNSUPPORTED_OCR_LANGUAGE"
    assert "action" in data


def test_extract_screenshot_rejects_oversized_file(client):
    # Streamed payload exceeds 5 MiB (5 * 1024 * 1024 + 100 bytes)
    oversized_bytes = b"0" * (5 * 1024 * 1024 + 100)
    response = client.post(
        "/api/v1/extract/screenshot",
        files={"file": ("large.png", oversized_bytes, "image/png")},
        data={"ocr_language": "eng"},
    )
    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "FILE_TOO_LARGE"
    assert "action" in data


def test_extract_screenshot_handles_invalid_image(client):
    corrupt_bytes = b"NOT_A_VALID_IMAGE_DATA_12345"
    response = client.post(
        "/api/v1/extract/screenshot",
        files={"file": ("fake.png", corrupt_bytes, "image/png")},
        data={"ocr_language": "eng"},
    )
    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "INVALID_IMAGE"


def test_extract_screenshot_handles_animated_image_rejection(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = AnimatedImageError()

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("animated.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 422
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.json()["code"] == "ANIMATED_IMAGE_REJECTED"


def test_extract_screenshot_handles_image_too_large(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = ImageTooLargeError()

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("giant.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 422
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.json()["code"] == "IMAGE_TOO_LARGE"


def test_extract_screenshot_handles_ocr_unavailable(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = OcrUnavailableError()

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 503
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "OCR_UNAVAILABLE"


def test_extract_screenshot_handles_language_not_installed(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = OcrLanguageNotInstalledError("hin")

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", b"fake", "image/png")},
            data={"ocr_language": "hin"},
        )
        assert response.status_code == 503
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "OCR_LANGUAGE_NOT_INSTALLED"


def test_extract_screenshot_handles_empty_extraction(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = EmptyExtractionError()

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 422
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "EMPTY_EXTRACTION"


def test_extract_screenshot_handles_text_too_long(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = TextTooLongError(12500)

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 422
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "TEXT_TOO_LONG"
        assert "12,500" in data["message"]


def test_extract_screenshot_handles_ocr_timeout(client):
    with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = OcrTimeoutError()

        response = client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", b"fake", "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 504
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert data["code"] == "OCR_TIMEOUT"


def test_no_outbound_network_or_gemini_call_during_extraction(monkeypatch, client):
    """
    Guarantees that extracting text does not touch Gemini, Google API, or outbound HTTP.
    """
    import httpx

    def forbidden_call(*args, **kwargs):
        raise AssertionError("Outbound network call was attempted during screenshot extraction!")

    monkeypatch.setattr(httpx, "get", forbidden_call)
    monkeypatch.setattr(httpx, "post", forbidden_call)

    with patch("google.genai.Client", side_effect=AssertionError("Google GenAI Client should never be initialized for OCR!")):
        png_bytes = create_test_image_bytes("PNG")
        mock_response = ScreenshotExtractionResponse(
            extracted_text="Test message.",
            ocr_language="eng",
            character_count=13,
            review_required=True,
            notice="Please review.",
        )
        with patch("app.api.v1.extract.OcrService.extract_text", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = mock_response

            res = client.post(
                "/api/v1/extract/screenshot",
                files={"file": ("test.png", png_bytes, "image/png")},
                data={"ocr_language": "eng"},
            )
            assert res.status_code == 200


def test_extract_screenshot_under_windows_selector_loop_regression():
    """
    Regression test for Uvicorn --reload startup mode on Windows:
    Demonstrates that the extraction endpoint succeeds under WindowsSelectorEventLoop
    and does NOT raise NotImplementedError or fail with OCR_EXECUTION_FAILED.
    """
    app = create_app()
    isolated_settings = Settings(
        ai_provider="none",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: isolated_settings

    test_client = TestClient(app)
    png_bytes = create_test_image_bytes("PNG")

    # Mock create_subprocess_exec raising NotImplementedError (as SelectorEventLoop does on Windows)
    with patch("app.services.ocr.find_tesseract_binary", return_value=r"C:\Program Files\Tesseract-OCR\tesseract.exe"), \
         patch("app.services.ocr.get_installed_languages", return_value=["eng", "hin"]), \
         patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError("Not implemented on SelectorEventLoop")), \
         patch("app.services.ocr._run_tesseract_process_sync", return_value=(0, "Congratulations! You have been selected for a remote job.", "")):

        response = test_client.post(
            "/api/v1/extract/screenshot",
            files={"file": ("screenshot.png", png_bytes, "image/png")},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 200
        assert response.headers.get("Cache-Control") == "no-store"
        data = response.json()
        assert "remote job" in data["extracted_text"]
        assert data["ocr_language"] == "eng"


def test_extract_screenshot_real_local_ocr_with_synthetic_fixture():
    """
    Real local OCR test through the HTTP extraction endpoint using installed Tesseract.
    Runs without mocks if Tesseract is installed; skipped if Tesseract is not installed.
    """
    from PIL import ImageDraw
    from app.services.ocr import find_tesseract_binary

    if not find_tesseract_binary():
        pytest.skip("Tesseract is not installed on this host.")

    app = create_app()
    isolated_settings = Settings(
        ai_provider="none",
        ai_model="gemini-3.5-flash-lite",
        ai_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: isolated_settings

    test_client = TestClient(app)

    # Generate synthetic image with clear black-on-white text
    img = Image.new("RGB", (500, 120), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), "FraudLens Test Job Offer Message", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    synthetic_png = buf.getvalue()

    response = test_client.post(
        "/api/v1/extract/screenshot",
        files={"file": ("synthetic_job.png", synthetic_png, "image/png")},
        data={"ocr_language": "eng"},
    )
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["ocr_language"] == "eng"
    assert data["character_count"] > 0
    assert data["review_required"] is True
    assert "review" in data["notice"].lower()


def test_upload_rejected_on_explicit_content_length_exceeded():
    """
    Verifies that requests with Content-Length exceeding the bounded upload limit
    are rejected immediately with HTTP 413 and Cache-Control: no-store.
    """
    app = create_app()
    test_client = TestClient(app)

    # Content-Length claiming 10 MiB
    oversized_length = 10 * 1024 * 1024
    response = test_client.post(
        "/api/v1/extract/screenshot",
        headers={
            "content-type": "multipart/form-data; boundary=bound123",
            "content-length": str(oversized_length),
        },
        content=b"--bound123--\r\n",
    )
    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "FILE_TOO_LARGE"
    assert "exceeds" in data["message"].lower()


def test_upload_rejected_on_streamed_oversized_body_without_content_length():
    """
    Verifies that chunked / streamed requests without Content-Length that exceed
    the upload limit are aborted mid-stream with HTTP 413 and Cache-Control: no-store.
    """
    app = create_app()
    test_client = TestClient(app)

    # 6 MiB of streamed data with absent content length (generator produces chunked transfer)
    def stream_chunks():
        yield b"X" * (3 * 1024 * 1024)
        yield b"X" * (3 * 1024 * 1024)

    response = test_client.post(
        "/api/v1/extract/screenshot",
        headers={"content-type": "multipart/form-data; boundary=bound123"},
        content=stream_chunks(),
    )
    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_upload_rejected_on_streamed_oversized_body_with_misleading_low_content_length():
    """
    Verifies that requests claiming a misleadingly low Content-Length (e.g. 200 bytes)
    that actually stream oversized bodies (> 5.06 MiB) are aborted mid-stream
    with HTTP 413 and Cache-Control: no-store.
    """
    import json
    app = create_app()

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/extract/screenshot",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=bound123"),
            (b"content-length", b"200"),
        ],
    }
    chunks = [
        b"--bound123\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.png\"\r\nContent-Type: image/png\r\n\r\n",
        b"A" * (3 * 1024 * 1024),
        b"B" * (3 * 1024 * 1024),
        b"\r\n--bound123--\r\n",
    ]
    chunk_iter = iter(chunks)

    async def receive():
        try:
            chunk = next(chunk_iter)
            return {"type": "http.request", "body": chunk, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(msg):
        messages.append(msg)

    await app(scope, receive, send)

    start_msg = next(m for m in messages if m["type"] == "http.response.start")
    assert start_msg["status"] == 413
    headers = dict(start_msg["headers"])
    assert headers.get(b"cache-control") == b"no-store"

    # Find response body message
    body_msg = next(m for m in messages if m["type"] == "http.response.body")
    data = json.loads(body_msg["body"].decode("utf-8"))
    assert data["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_streamed_oversized_multipart_closes_created_spool_files():
    """
    Demonstrates that when streamed oversized multipart bodies trigger
    StreamingPayloadTooLargeError, Starlette's MultiPartParser catches the exception
    and executes close() on all partially created SpooledTemporaryFile spool files.
    """
    import tempfile
    import json
    app = create_app()

    # Construct multipart stream where header chunk initiates a SpooledTemporaryFile
    chunks = [
        b'--bound123\r\nContent-Disposition: form-data; name="file"; filename="test.png"\r\nContent-Type: image/png\r\n\r\n',
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
        "path": "/api/v1/extract/screenshot",
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
    # Proves the spool file created during parsing was closed by the parser's cleanup path
    assert len(close_calls) >= 1


def test_upload_rejected_on_excess_multipart_parts():
    """
    Verifies that requests with excess multipart parts (> 1000 fields) triggering
    MultiPartException are safely mapped to HTTP 400 with Cache-Control: no-store.
    """
    app = create_app()
    test_client = TestClient(app)

    # 1500 small fields
    parts = b"".join(
        [f"--bound\r\nContent-Disposition: form-data; name=\"field{i}\"\r\n\r\nval{i}\r\n".encode() for i in range(1200)]
    ) + b"--bound--\r\n"

    response = test_client.post(
        "/api/v1/extract/screenshot",
        headers={"content-type": "multipart/form-data; boundary=bound"},
        content=parts,
    )
    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "INVALID_MULTIPART_REQUEST"


def test_upload_rejected_on_unexpected_form_fields():
    """
    Verifies that requests with unexpected multipart form fields are rejected
    with HTTP 422 and Cache-Control: no-store.
    """
    app = create_app()
    test_client = TestClient(app)
    png_bytes = create_test_image_bytes("PNG")

    response = test_client.post(
        "/api/v1/extract/screenshot",
        files={"file": ("test.png", png_bytes, "image/png")},
        data={"ocr_language": "eng", "malicious_extra_field": "injected_payload"},
    )
    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "UNEXPECTED_MULTIPART_FIELDS"
    assert "malicious_extra_field" in data["message"]


def test_upload_rejected_on_multiple_files():
    """
    Verifies that multipart requests attempting to upload multiple files
    are rejected with HTTP 422 and Cache-Control: no-store.
    """
    app = create_app()
    test_client = TestClient(app)
    png_bytes = create_test_image_bytes("PNG")

    response = test_client.post(
        "/api/v1/extract/screenshot",
        files=[
            ("file", ("img1.png", png_bytes, "image/png")),
            ("file", ("img2.png", png_bytes, "image/png")),
        ],
        data={"ocr_language": "eng"},
    )
    assert response.status_code == 422
    assert response.headers.get("Cache-Control") == "no-store"
    data = response.json()
    assert data["code"] == "MULTIPLE_FILES_REJECTED"

