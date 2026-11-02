import asyncio
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from PIL import Image

from app.services.ocr import (
    AnimatedImageError,
    EmptyExtractionError,
    FileTooLargeError,
    ImageTooLargeError,
    InvalidImageError,
    MAX_IMAGE_FILE_SIZE,
    MAX_IMAGE_PIXELS,
    OcrExecutionError,
    OcrLanguageNotInstalledError,
    OcrService,
    OcrTimeoutError,
    OcrUnavailableError,
    TextTooLongError,
    check_ocr_availability,
    find_tesseract_binary,
    get_installed_languages,
)


def create_test_image_bytes(format="PNG", size=(100, 100), color=(255, 0, 0)) -> bytes:
    """Helper to generate in-memory image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    return buf.getvalue()


def test_validate_and_preprocess_valid_png():
    service = OcrService()
    png_bytes = create_test_image_bytes("PNG", size=(50, 50))
    preprocessed = service.validate_and_preprocess_image(png_bytes)
    assert isinstance(preprocessed, bytes)
    assert len(preprocessed) > 0
    # Preprocessed result is a valid PNG
    with Image.open(io.BytesIO(preprocessed)) as img:
        assert img.format == "PNG"
        assert img.size == (50, 50)


def test_validate_and_preprocess_valid_jpeg():
    service = OcrService()
    jpeg_bytes = create_test_image_bytes("JPEG", size=(80, 60))
    preprocessed = service.validate_and_preprocess_image(jpeg_bytes)
    assert isinstance(preprocessed, bytes)
    assert len(preprocessed) > 0
    # Preprocessed result normalized to PNG
    with Image.open(io.BytesIO(preprocessed)) as img:
        assert img.format == "PNG"
        assert img.size == (80, 60)


def test_rejects_empty_file():
    service = OcrService()
    with pytest.raises(InvalidImageError) as exc_info:
        service.validate_and_preprocess_image(b"")
    assert exc_info.value.code == "INVALID_IMAGE"


def test_rejects_file_exceeding_5mb():
    service = OcrService()
    oversized = b"x" * (MAX_IMAGE_FILE_SIZE + 1)
    with pytest.raises(FileTooLargeError) as exc_info:
        service.validate_and_preprocess_image(oversized)
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.http_status == 413


def test_rejects_corrupt_or_non_image_bytes():
    service = OcrService()
    fake_png = b"Not a real PNG header at all"
    with pytest.raises(InvalidImageError) as exc_info:
        service.validate_and_preprocess_image(fake_png)
    assert exc_info.value.code == "INVALID_IMAGE"


def test_rejects_unsupported_image_formats():
    service = OcrService()
    # BMP format
    buf = io.BytesIO()
    img = Image.new("RGB", (20, 20), color="blue")
    img.save(buf, format="BMP")
    bmp_bytes = buf.getvalue()

    with pytest.raises(InvalidImageError) as exc_info:
        service.validate_and_preprocess_image(bmp_bytes)
    assert exc_info.value.code == "INVALID_IMAGE"
    assert "Unsupported image format" in exc_info.value.message


def test_rejects_multiframe_or_animated_images():
    service = OcrService()
    # Create multi-frame GIF
    buf = io.BytesIO()
    frame1 = Image.new("RGB", (20, 20), color="red")
    frame2 = Image.new("RGB", (20, 20), color="blue")
    frame1.save(
        buf,
        format="GIF",
        save_all=True,
        append_images=[frame2],
        duration=100,
        loop=0,
    )
    gif_bytes = buf.getvalue()

    with pytest.raises((AnimatedImageError, InvalidImageError)) as exc_info:
        service.validate_and_preprocess_image(gif_bytes)
    assert exc_info.value.code in ("ANIMATED_IMAGE_REJECTED", "INVALID_IMAGE")


def test_rejects_images_exceeding_12_megapixels():
    service = OcrService()
    # Mock Image.open to simulate image with > 12 MP dimensions without allocating gigabytes of RAM
    mock_img = MagicMock()
    mock_img.format = "PNG"
    mock_img.is_animated = False
    mock_img.n_frames = 1
    mock_img.size = (4000, 3001)  # 12,004,000 pixels (> 12,000,000)
    mock_img.__enter__.return_value = mock_img
    mock_img.__exit__.return_value = None

    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ImageTooLargeError) as exc_info:
            service.validate_and_preprocess_image(b"dummy_bytes")
        assert exc_info.value.code == "IMAGE_TOO_LARGE"
        assert exc_info.value.http_status == 422


def test_detect_tesseract_binary_none_when_missing():
    with patch("os.path.isfile", return_value=False), patch("shutil.which", return_value=None):
        binary = find_tesseract_binary()
        assert binary is None


def test_detect_tesseract_binary_finds_path():
    fake_path = r"C:\Custom\Tesseract\tesseract.exe"
    with patch("os.path.isfile", side_effect=lambda p: p == fake_path):
        binary = find_tesseract_binary(custom_path=fake_path)
        assert binary == fake_path


def test_get_installed_languages_parses_output():
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "List of available languages (3):\neng\nhin\nosd\n"

    with patch("subprocess.run", return_value=mock_res):
        langs = get_installed_languages("fake_tesseract")
        assert "eng" in langs
        assert "hin" in langs
        assert "osd" in langs


def test_check_ocr_availability_reports_truthfully():
    # When missing
    with patch("app.services.ocr.find_tesseract_binary", return_value=None):
        avail, langs, status = check_ocr_availability()
        assert avail is False
        assert langs == []
        assert status == "missing_prerequisites"

    # When present with eng and hin
    with patch("app.services.ocr.find_tesseract_binary", return_value="/bin/tesseract"), \
         patch("app.services.ocr.get_installed_languages", return_value=["eng", "hin", "osd"]):
        avail, langs, status = check_ocr_availability()
        assert avail is True
        assert langs == ["eng", "hin"]
        assert status == "ready"

    # When present but missing eng
    with patch("app.services.ocr.find_tesseract_binary", return_value="/bin/tesseract"), \
         patch("app.services.ocr.get_installed_languages", return_value=["deu", "fra"]):
        avail, langs, status = check_ocr_availability()
        assert avail is False
        assert langs == []
        assert status == "missing_prerequisites"


@pytest.mark.asyncio
async def test_extract_text_raises_when_tesseract_unavailable():
    service = OcrService()
    service._tesseract_cmd = None
    png_bytes = create_test_image_bytes("PNG")

    with pytest.raises(OcrUnavailableError) as exc_info:
        await service.extract_text(png_bytes, "eng")
    assert exc_info.value.code == "OCR_UNAVAILABLE"
    assert exc_info.value.http_status == 503


@pytest.mark.asyncio
async def test_extract_text_raises_when_requested_language_not_installed():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"
    png_bytes = create_test_image_bytes("PNG")

    with patch("app.services.ocr.get_installed_languages", return_value=["eng"]):
        with pytest.raises(OcrLanguageNotInstalledError) as exc_info:
            await service.extract_text(png_bytes, "hin")
        assert exc_info.value.code == "OCR_LANGUAGE_NOT_INSTALLED"
        assert exc_info.value.http_status == 503


@pytest.mark.asyncio
async def test_extract_text_raises_on_empty_extraction():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"
    png_bytes = create_test_image_bytes("PNG")

    with patch("app.services.ocr.get_installed_languages", return_value=["eng", "hin"]), \
         patch.object(service, "_execute_tesseract_subprocess", new_callable=AsyncMock) as mock_exec:
        # Tesseract returns whitespace only
        mock_exec.return_value = "   \n\t  "

        with pytest.raises(EmptyExtractionError) as exc_info:
            await service.extract_text(png_bytes, "eng")
        assert exc_info.value.code == "EMPTY_EXTRACTION"
        assert exc_info.value.http_status == 422


@pytest.mark.asyncio
async def test_extract_text_raises_when_over_10000_chars():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"
    png_bytes = create_test_image_bytes("PNG")

    with patch("app.services.ocr.get_installed_languages", return_value=["eng"]), \
         patch.object(service, "_execute_tesseract_subprocess", new_callable=AsyncMock) as mock_exec:
        # Return 10,001 characters
        mock_exec.return_value = "a" * 10001

        with pytest.raises(TextTooLongError) as exc_info:
            await service.extract_text(png_bytes, "eng")
        assert exc_info.value.code == "TEXT_TOO_LONG"
        assert exc_info.value.http_status == 422


@pytest.mark.asyncio
async def test_extract_text_success_flow():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"
    png_bytes = create_test_image_bytes("PNG")
    sample_text = "Dear Customer, your bank account has been suspended. Click here to verify."

    with patch("app.services.ocr.get_installed_languages", return_value=["eng"]), \
         patch.object(service, "_execute_tesseract_subprocess", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = f"\n  {sample_text}  \n"

        response = await service.extract_text(png_bytes, "eng")
        assert response.extracted_text == sample_text
        assert response.ocr_language == "eng"
        assert response.character_count == len(sample_text)
        assert response.review_required is True
        assert "review" in response.notice.lower()


@pytest.mark.asyncio
async def test_temporary_file_cleaned_up_after_extraction():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"
    png_bytes = create_test_image_bytes("PNG")

    captured_temp_path = None

    async def fake_execute(image_path, lang):
        nonlocal captured_temp_path
        captured_temp_path = image_path
        assert os.path.exists(image_path)
        return "Extracted valid message text."

    with patch("app.services.ocr.get_installed_languages", return_value=["eng"]), \
         patch.object(service, "_execute_tesseract_subprocess", side_effect=fake_execute):
        await service.extract_text(png_bytes, "eng")

        # After extract_text completes, temp file MUST be deleted
        assert captured_temp_path is not None
        assert not os.path.exists(captured_temp_path)


@pytest.mark.asyncio
async def test_subprocess_timeout_terminates_process():
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    # Mock process that hangs until killed
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        with pytest.raises(OcrTimeoutError) as exc_info:
            await service._execute_tesseract_subprocess("fake_image.png", "eng")

        assert exc_info.value.code == "OCR_TIMEOUT"
        assert exc_info.value.http_status == 504
        # Process kill must have been called
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_subprocess_execution_on_selector_loop_fallback():
    """
    Regression test for Windows Uvicorn --reload startup mode:
    Verifies that when the running loop is a SelectorEventLoop (or raises NotImplementedError
    on asyncio.create_subprocess_exec), the service executes via the thread-based runner.
    """
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    # Simulate SelectorEventLoop NotImplementedError on create_subprocess_exec
    with patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError("Not supported")), \
         patch("app.services.ocr._run_tesseract_process_sync", return_value=(0, "Recognized text from thread runner", "")):
        output = await service._execute_tesseract_subprocess("fake_image.png", "eng")
        assert output == "Recognized text from thread runner"


@pytest.mark.asyncio
async def test_thread_runner_timeout_terminates_process():
    """
    Verifies that if the thread runner times out, the child process is killed and reaped.
    """
    import subprocess
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()

    def fake_sync_run(cmd, img, lang, timeout, proc_holder):
        proc_holder[0] = mock_proc
        raise subprocess.TimeoutExpired(cmd, timeout)

    # Force using thread runner
    with patch("app.services.ocr._run_tesseract_process_sync", side_effect=fake_sync_run), \
         patch("sys.platform", "win32"), \
         patch("asyncio.get_running_loop", return_value=asyncio.SelectorEventLoop()):
        with pytest.raises(OcrTimeoutError) as exc_info:
            await service._execute_tesseract_subprocess("fake_image.png", "eng")

        assert exc_info.value.code == "OCR_TIMEOUT"
        assert exc_info.value.http_status == 504
        mock_proc.kill.assert_called()
        mock_proc.wait.assert_called()


@pytest.mark.asyncio
async def test_runner_cancelled_before_subprocess_creation():
    """
    Race condition 1: Task/runner is cancelled before subprocess creation begins.
    Verifies that CancelledError is raised and no process is spawned.
    """
    from app.services.ocr import _SyncOcrRunner

    runner = _SyncOcrRunner("/bin/tesseract", "dummy.png", "eng", 10.0)
    runner.cancel()

    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(asyncio.CancelledError):
            runner.run()
        mock_popen.assert_not_called()


@pytest.mark.asyncio
async def test_runner_cancelled_during_process_assignment():
    """
    Race condition 2: Process is being assigned right as cancellation arrives.
    Verifies process is immediately killed and reaped.
    """
    from app.services.ocr import _SyncOcrRunner

    runner = _SyncOcrRunner("/bin/tesseract", "dummy.png", "eng", 10.0)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    runner.cancel()
    runner[0] = mock_proc

    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_called_once()


@pytest.mark.asyncio
async def test_subprocess_cancelled_during_execution_reaps_process():
    """
    Race condition 3: Coroutine is cancelled while waiting for OCR execution.
    Verifies child process is killed and reaped, and CancelledError propagates.
    """
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()

    async def run_with_cancellation():
        coro = service._execute_tesseract_subprocess("fake_image.png", "eng")
        task = asyncio.create_task(coro)
        await asyncio.sleep(0.01)
        task.cancel()
        await task

    def hanging_sync_run(cmd, img, lang, timeout, proc_holder):
        proc_holder[0] = mock_proc
        # Sleep briefly to simulate execution before cancellation
        import time
        time.sleep(0.2)
        return (0, "text", "")

    with patch("app.services.ocr._run_tesseract_process_sync", side_effect=hanging_sync_run), \
         patch("sys.platform", "win32"), \
         patch("asyncio.get_running_loop", return_value=asyncio.SelectorEventLoop()):
        with pytest.raises(asyncio.CancelledError):
            await run_with_cancellation()

    mock_proc.kill.assert_called()
    mock_proc.wait.assert_called()


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_concurrency_semaphore():
    """
    Race condition 4: Cancellation occurs while waiting to acquire _ocr_semaphore.
    Verifies semaphore slots are not leaked, and remaining tasks acquire cleanly.
    """
    from app.services.ocr import _ocr_semaphore

    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    # Acquire all 3 slots
    await _ocr_semaphore.acquire()
    await _ocr_semaphore.acquire()
    await _ocr_semaphore.acquire()
    assert _ocr_semaphore.locked()

    # Launch a 4th task that must wait on the semaphore
    task = asyncio.create_task(service._execute_tesseract_subprocess("fake.png", "eng"))
    await asyncio.sleep(0.02)
    assert not task.done()

    # Cancel the waiting 4th task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Release the 3 slots and verify semaphore count returns to 3
    _ocr_semaphore.release()
    _ocr_semaphore.release()
    _ocr_semaphore.release()

    # Verify we can acquire all 3 slots again cleanly
    assert not _ocr_semaphore.locked()
    await _ocr_semaphore.acquire()
    await _ocr_semaphore.acquire()
    await _ocr_semaphore.acquire()
    _ocr_semaphore.release()
    _ocr_semaphore.release()
    _ocr_semaphore.release()


@pytest.mark.asyncio
async def test_event_loop_responsiveness_during_delayed_process_creation():
    """
    Verifies that neither mutex acquisition during delayed Popen nor cancel()
    blocks the asyncio event loop. Concurrent async tasks must continue ticking.
    """
    import time
    from app.services.ocr import _SyncOcrRunner

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()

    def delayed_popen(*args, **kwargs):
        time.sleep(0.15)
        return mock_proc

    runner = _SyncOcrRunner("/bin/tesseract", "dummy.png", "eng", 10.0)

    ticks = 0
    stop_ticker = False

    async def event_loop_ticker():
        nonlocal ticks
        while not stop_ticker:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker_task = asyncio.create_task(event_loop_ticker())

    with patch("subprocess.Popen", side_effect=delayed_popen):
        worker_task = asyncio.create_task(asyncio.to_thread(runner.run))
        # Let Popen begin running in thread
        await asyncio.sleep(0.04)

        # Cancel while Popen is actively running in background thread
        runner.cancel()

        # Concurrently ensure event loop keeps ticking
        await asyncio.sleep(0.12)
        stop_ticker = True
        await ticker_task

        # Worker thread must finish cleanly
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Event loop ticked multiple times without blocking
    assert ticks >= 5
    mock_proc.kill.assert_called()
    mock_proc.wait.assert_called()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_cleanup_preserves_worker_completion():
    """
    Verifies that repeated cancellations during cleanup cannot bypass worker completion.
    The worker task must finish and reap child processes before semaphore release.
    """
    import time
    service = OcrService()
    service._tesseract_cmd = "/bin/tesseract"

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()

    worker_finished = False

    def slow_cleanup_sync_run(cmd, img, lang, timeout, proc_holder):
        proc_holder[0] = mock_proc
        time.sleep(0.15)
        nonlocal worker_finished
        worker_finished = True
        return (0, "text", "")

    with patch("app.services.ocr._run_tesseract_process_sync", side_effect=slow_cleanup_sync_run), \
         patch("sys.platform", "win32"), \
         patch("asyncio.get_running_loop", return_value=asyncio.SelectorEventLoop()):

        task = asyncio.create_task(service._execute_tesseract_subprocess("fake.png", "eng"))
        await asyncio.sleep(0.02)

        # Fire multiple cancellations in rapid succession
        task.cancel()
        task.cancel()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # When the task finally completes, worker MUST have finished completely
        assert worker_finished is True
        mock_proc.kill.assert_called()
        mock_proc.wait.assert_called()



