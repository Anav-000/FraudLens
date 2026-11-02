import asyncio
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple
from PIL import Image, ImageOps

from app.schemas.ocr import OcrLanguage, ScreenshotExtractionResponse

# Limits and constants enforced for security and resource bounds
MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB
MAX_IMAGE_PIXELS = 12_000_000  # 12 megapixels max decoded size
MAX_EXTRACTED_CHARACTERS = 10_000  # Must match analysis limit
OCR_TIMEOUT_SECONDS = 20.0  # Execution timeout
ALLOWED_IMAGE_FORMATS: Set[str] = {"PNG", "JPEG"}
SUPPORTED_OCR_LANGUAGES: Set[str] = {"eng", "hin"}

# Bounded concurrency to avoid overwhelming CPU with concurrent OCR tasks
_ocr_semaphore = asyncio.Semaphore(3)


class OcrServiceError(Exception):
    """
    Base exception for all sanitized OCR service errors.
    Contains stable machine codes and safe actionable user advice.
    """
    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        reason: Optional[str] = None,
        http_status: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.reason = reason
        self.http_status = http_status


class FileTooLargeError(OcrServiceError):
    def __init__(self, message: str = "Image file exceeds the maximum allowed size of 5 MiB."):
        super().__init__(
            code="FILE_TOO_LARGE",
            message=message,
            action="Compress, crop, or resize the screenshot before uploading.",
            http_status=413,
        )


class InvalidImageError(OcrServiceError):
    def __init__(self, message: str = "Corrupt image or unsupported file format. Only PNG and JPEG are supported."):
        super().__init__(
            code="INVALID_IMAGE",
            message=message,
            action="Please select a valid, uncorrupted PNG or JPEG screenshot.",
            http_status=422,
        )


class ImageTooLargeError(OcrServiceError):
    def __init__(self, message: str = "Image dimensions exceed the maximum decoded limit of 12 megapixels."):
        super().__init__(
            code="IMAGE_TOO_LARGE",
            message=message,
            action="Crop or scale down the screenshot before uploading.",
            http_status=422,
        )


class AnimatedImageError(OcrServiceError):
    def __init__(self, message: str = "Animated or multi-frame images are not supported."):
        super().__init__(
            code="ANIMATED_IMAGE_REJECTED",
            message=message,
            action="Please upload a single-frame static PNG or JPEG screenshot.",
            http_status=422,
        )


class OcrUnavailableError(OcrServiceError):
    def __init__(self, message: str = "Tesseract OCR engine is not installed or available on this host."):
        super().__init__(
            code="OCR_UNAVAILABLE",
            message=message,
            action="Install Tesseract-OCR on the server host to enable screenshot extraction.",
            http_status=503,
        )


class OcrLanguageNotInstalledError(OcrServiceError):
    def __init__(self, language: str):
        super().__init__(
            code="OCR_LANGUAGE_NOT_INSTALLED",
            message=f"OCR language data for '{language}' is not installed on this server.",
            action=f"Install the {language}.traineddata language pack in Tesseract's tessdata directory.",
            http_status=503,
        )


class EmptyExtractionError(OcrServiceError):
    def __init__(self):
        super().__init__(
            code="EMPTY_EXTRACTION",
            message="No legible text could be extracted from the provided screenshot.",
            action="Ensure the screenshot is upright, high-contrast, and clearly displays message text.",
            http_status=422,
        )


class TextTooLongError(OcrServiceError):
    def __init__(self, char_count: int):
        super().__init__(
            code="TEXT_TOO_LONG",
            message=f"Extracted text exceeds the maximum limit of {MAX_EXTRACTED_CHARACTERS:,} characters ({char_count:,} characters extracted).",
            action="Crop the screenshot to focus on the specific suspicious message text.",
            http_status=422,
        )


class OcrTimeoutError(OcrServiceError):
    def __init__(self):
        super().__init__(
            code="OCR_TIMEOUT",
            message=f"Screenshot text extraction timed out after {int(OCR_TIMEOUT_SECONDS)} seconds.",
            action="Try cropping the screenshot to a smaller region or paste the text directly.",
            http_status=504,
        )


class OcrExecutionError(OcrServiceError):
    def __init__(
        self,
        message: str = "An error occurred while executing optical character recognition.",
        reason: Optional[str] = "SUBPROCESS_FAILED",
    ):
        super().__init__(
            code="OCR_EXECUTION_FAILED",
            message=message,
            action="Try again with a cropped or clearer screenshot, or paste the text directly.",
            reason=reason,
            http_status=500,
        )


def find_tesseract_binary(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Locates the Tesseract executable on the system without throwing exceptions.
    Checks:
    1. Custom path if provided
    2. TESSERACT_CMD environment variable
    3. System PATH via shutil.which
    4. Common Windows default installation directories
    """
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd

    which_cmd = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if which_cmd and os.path.isfile(which_cmd):
        return which_cmd

    # Standard Windows install locations
    windows_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
    ]
    for candidate in windows_candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def get_installed_languages(tesseract_binary: str) -> List[str]:
    """
    Queries tesseract for installed traineddata languages.
    """
    try:
        import subprocess
        result = subprocess.run(
            [tesseract_binary, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if result.returncode != 0:
            return []
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        # Typically the first line is "List of available languages (n):"
        languages = []
        for line in lines:
            if "languages" in line.lower() or line.startswith("="):
                continue
            languages.append(line)
        return languages
    except Exception:
        return []


def check_ocr_availability(custom_path: Optional[str] = None) -> Tuple[bool, List[str], str]:
    """
    Fast, non-blocking check for OCR availability and installed languages.
    Never runs OCR inference or external network calls.
    Returns: (is_available, supported_installed_languages, prerequisite_status)
    """
    binary = find_tesseract_binary(custom_path)
    if not binary:
        return False, [], "missing_prerequisites"

    installed = get_installed_languages(binary)
    # Check which of our supported languages ('eng', 'hin') are present
    supported = [lang for lang in ["eng", "hin"] if lang in installed]

    # At least 'eng' must be installed for baseline availability
    if "eng" in supported:
        return True, supported, "ready"
    return False, supported, "missing_prerequisites"


class _SyncOcrRunner:
    """
    Thread-safe runner that coordinates synchronous Popen execution in a worker thread.
    Guarantees:
    - cancel() never blocks the asyncio event loop (mutex does not span Popen; no synchronous waits).
    - cancel() before, during, or after process creation terminates and reaps child processes.
    - Process reaping (proc.wait()) is performed by the worker thread pool, not the event loop.
    - No orphan process survives cancellation or timeout.
    """
    def __init__(
        self,
        tesseract_cmd: str,
        image_path: str,
        ocr_language: str,
        timeout: float,
    ):
        self.tesseract_cmd = tesseract_cmd
        self.image_path = image_path
        self.ocr_language = ocr_language
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._done = threading.Event()

    def __getitem__(self, index: int) -> Optional[subprocess.Popen]:
        return self.proc

    def __setitem__(self, index: int, val: Optional[subprocess.Popen]) -> None:
        with self._lock:
            self.proc = val
            if self._cancel_event.is_set() and val is not None:
                try:
                    if val.poll() is None:
                        val.kill()
                    val.wait()
                except OSError:
                    pass

    def run(self) -> Tuple[int, str, str]:
        # Check cancellation before process creation begins
        if self._cancel_event.is_set():
            self._done.set()
            raise asyncio.CancelledError("OCR process cancelled prior to subprocess creation.")

        try:
            # Process creation runs without holding the mutex across Popen
            proc = subprocess.Popen(
                [self.tesseract_cmd, self.image_path, "stdout", "-l", self.ocr_language],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            self._done.set()
            raise

        # Atomically register process reference
        with self._lock:
            self.proc = proc

        # Check if cancellation arrived while Popen was executing
        if self._cancel_event.is_set():
            self._terminate_and_reap()
            self._done.set()
            raise asyncio.CancelledError("OCR process cancelled during subprocess creation.")

        try:
            stdout, stderr = self.proc.communicate(timeout=self.timeout)
            return self.proc.returncode, stdout, stderr
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
        Signals cancellation and terminates process nonblockingly.
        Does not block on process creation or synchronous wait().
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


def _run_tesseract_process_sync(
    tesseract_cmd: str,
    image_path: str,
    ocr_language: str,
    timeout: float,
    proc_holder: Any,
) -> Tuple[int, str, str]:
    """
    Synchronous subprocess runner executed in a worker thread.
    Safely runs tesseract regardless of event loop implementation (including
    asyncio.SelectorEventLoop on Windows under Uvicorn --reload).
    Ensures process termination and reaping on timeout.
    """
    if isinstance(proc_holder, _SyncOcrRunner):
        return proc_holder.run()

    proc = subprocess.Popen(
        [tesseract_cmd, image_path, "stdout", "-l", ocr_language],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if isinstance(proc_holder, list) and len(proc_holder) > 0:
        proc_holder[0] = proc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        except OSError:
            pass
        raise
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        except OSError:
            pass


class OcrService:
    """
    Service adapter for local optical character recognition.
    Enforces strict file constraints, Pillow decompression protection,
    bounded subprocess timeouts, and automatic resource cleanup.
    Never makes network requests or contacts Google Gemini.
    """
    def __init__(self, tesseract_cmd: Optional[str] = None):
        self._tesseract_cmd = find_tesseract_binary(tesseract_cmd)

    def is_available(self) -> bool:
        return self._tesseract_cmd is not None

    def validate_and_preprocess_image(self, file_bytes: bytes) -> bytes:
        """
        Validates raw image bytes and prepares them safely for OCR:
        - Checks raw byte size against 5 MiB limit.
        - Protects against Pillow decompression bombs.
        - Verifies format is strictly PNG or JPEG.
        - Rejects animated / multi-frame images.
        - Checks decoded pixel dimension (max 12 megapixels).
        - Transposes EXIF orientation for upright text.
        - Normalizes image mode to RGB.
        Returns preprocessed PNG bytes.
        """
        if len(file_bytes) > MAX_IMAGE_FILE_SIZE:
            raise FileTooLargeError()

        if len(file_bytes) == 0:
            raise InvalidImageError("Uploaded file is empty.")

        # Configure Pillow decompression bomb protection
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

        try:
            image_stream = io.BytesIO(file_bytes)
            with Image.open(image_stream) as img:
                # Strictly verify image format
                if img.format not in ALLOWED_IMAGE_FORMATS:
                    raise InvalidImageError(
                        f"Unsupported image format: {img.format or 'unknown'}. Only PNG and JPEG are supported."
                    )

                # Reject multi-frame or animated images
                n_frames = getattr(img, "n_frames", 1)
                is_multi_frame = isinstance(n_frames, int) and n_frames > 1
                if bool(getattr(img, "is_animated", False)) or is_multi_frame:
                    raise AnimatedImageError()

                # Check pixel limits
                width, height = img.size
                pixel_count = width * height
                if pixel_count > MAX_IMAGE_PIXELS:
                    raise ImageTooLargeError(
                        f"Image size of {pixel_count:,} pixels ({width}x{height}) exceeds limit of {MAX_IMAGE_PIXELS:,} pixels."
                    )

                # Normalize orientation based on EXIF tag
                normalized = ImageOps.exif_transpose(img)
                if normalized is None:
                    normalized = img

                # Normalize color mode to RGB for consistent OCR
                if normalized.mode not in ("RGB", "L"):
                    normalized = normalized.convert("RGB")

                # Export preprocessed image to a fresh PNG memory buffer
                output_buffer = io.BytesIO()
                normalized.save(output_buffer, format="PNG")
                return output_buffer.getvalue()

        except (ImageTooLargeError, FileTooLargeError, AnimatedImageError, InvalidImageError):
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ImageTooLargeError("Image triggered decompression bomb security protection.")
        except Exception:
            raise InvalidImageError("Could not decode image. The file may be corrupt or invalid.")

    async def _execute_tesseract_subprocess(
        self,
        image_path: str,
        ocr_language: OcrLanguage,
    ) -> str:
        """
        Executes Tesseract CLI in a subprocess with strict timeout handling.
        Terminates the child process on timeout.
        Compatible with both ProactorEventLoop and SelectorEventLoop on Windows.
        """
        if not self._tesseract_cmd:
            raise OcrUnavailableError()

        # Run with bounded concurrency
        async with _ocr_semaphore:
            loop = asyncio.get_running_loop()
            is_windows_selector = sys.platform == "win32" and isinstance(
                loop, getattr(asyncio, "SelectorEventLoop", ())
            )

            if not is_windows_selector:
                proc = None
                try:
                    proc = await asyncio.create_subprocess_exec(
                        self._tesseract_cmd,
                        image_path,
                        "stdout",
                        "-l",
                        ocr_language,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout_b, stderr_b = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=OCR_TIMEOUT_SECONDS,
                    )

                    if proc.returncode != 0:
                        stderr_text = stderr_b.decode("utf-8", errors="replace").lower()
                        if "failed loading language" in stderr_text or f"data for {ocr_language}" in stderr_text:
                            raise OcrLanguageNotInstalledError(ocr_language)
                        raise OcrExecutionError(
                            "Tesseract OCR execution failed.",
                            reason="SUBPROCESS_NONZERO_EXIT",
                        )

                    return stdout_b.decode("utf-8", errors="replace")

                except NotImplementedError:
                    # In case of custom loop or unexpected NotImplementedError, fall through to thread runner
                    pass
                except asyncio.TimeoutError:
                    if proc is not None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except (ProcessLookupError, OSError):
                            pass
                    raise OcrTimeoutError()
                except asyncio.CancelledError:
                    if proc is not None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except (ProcessLookupError, OSError):
                            pass
                    raise
                except (OcrServiceError, OcrLanguageNotInstalledError, OcrTimeoutError, OcrExecutionError):
                    raise
                except Exception as exc:
                    if proc is not None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except (ProcessLookupError, OSError):
                            pass
                    raise OcrExecutionError(
                        "Tesseract OCR execution failed.",
                        reason="SUBPROCESS_EXECUTION_ERROR",
                    ) from exc

            # Thread-based subprocess execution for SelectorEventLoop (e.g. Uvicorn --reload on Windows)
            runner = _SyncOcrRunner(
                self._tesseract_cmd,
                image_path,
                ocr_language,
                OCR_TIMEOUT_SECONDS,
            )
            worker_task = asyncio.create_task(
                asyncio.to_thread(
                    _run_tesseract_process_sync,
                    self._tesseract_cmd,
                    image_path,
                    ocr_language,
                    OCR_TIMEOUT_SECONDS,
                    runner,
                )
            )
            try:
                returncode, stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(worker_task),
                    timeout=OCR_TIMEOUT_SECONDS + 1.0,
                )

                if returncode != 0:
                    stderr_text = stderr.lower()
                    if "failed loading language" in stderr_text or f"data for {ocr_language}" in stderr_text:
                        raise OcrLanguageNotInstalledError(ocr_language)
                    raise OcrExecutionError(
                        "Tesseract OCR execution failed.",
                        reason="SUBPROCESS_NONZERO_EXIT",
                    )

                return stdout

            except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                runner.cancel()
                while not worker_task.done():
                    try:
                        await asyncio.shield(worker_task)
                    except (asyncio.CancelledError, Exception):
                        pass
                await asyncio.to_thread(runner._terminate_and_reap)
                raise OcrTimeoutError()
            except asyncio.CancelledError:
                runner.cancel()
                while not worker_task.done():
                    try:
                        await asyncio.shield(worker_task)
                    except (asyncio.CancelledError, Exception):
                        pass
                await asyncio.to_thread(runner._terminate_and_reap)
                raise
            except (OcrServiceError, OcrLanguageNotInstalledError, OcrTimeoutError, OcrExecutionError):
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
                raise OcrExecutionError(
                    "Tesseract OCR execution failed.",
                    reason="SUBPROCESS_EXECUTION_ERROR",
                ) from exc

    async def extract_text(
        self,
        file_bytes: bytes,
        ocr_language: OcrLanguage = "eng",
    ) -> ScreenshotExtractionResponse:
        """
        Coordinates full screenshot extraction:
        1. Validates and preprocesses image bytes in memory.
        2. Verifies OCR engine availability and language pack.
        3. Writes temporary preprocessed file and executes Tesseract with subprocess timeout.
        4. Cleans up temporary resources unconditionally in finally block.
        5. Validates character count (max 10,000 characters) and checks for empty text.
        6. Returns structured ScreenshotExtractionResponse.
        """
        if ocr_language not in SUPPORTED_OCR_LANGUAGES:
            raise OcrServiceError(
                code="UNSUPPORTED_OCR_LANGUAGE",
                message=f"OCR language '{ocr_language}' is not supported. Choose 'eng' or 'hin'.",
                action="Select either English (eng) or Hindi (hin).",
                http_status=422,
            )

        # Preprocess and validate image in memory before OCR execution
        preprocessed_bytes = self.validate_and_preprocess_image(file_bytes)

        if not self._tesseract_cmd:
            raise OcrUnavailableError()

        # Check installed languages for requested language
        installed_langs = get_installed_languages(self._tesseract_cmd)
        if installed_langs and ocr_language not in installed_langs:
            raise OcrLanguageNotInstalledError(ocr_language)

        # Write to temporary file for Tesseract subprocess
        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp_path = temp_file.name
        try:
            temp_file.write(preprocessed_bytes)
            temp_file.flush()
            temp_file.close()

            raw_text = await self._execute_tesseract_subprocess(temp_path, ocr_language)

        finally:
            # Guaranteed cleanup of temporary image file on success, error, or timeout
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        # Normalize extracted text
        extracted_text = raw_text.strip()
        if not extracted_text:
            raise EmptyExtractionError()

        char_count = len(extracted_text)
        if char_count > MAX_EXTRACTED_CHARACTERS:
            raise TextTooLongError(char_count)

        return ScreenshotExtractionResponse(
            extracted_text=extracted_text,
            ocr_language=ocr_language,
            character_count=char_count,
            review_required=True,
            notice=(
                "Please review and edit the extracted text. "
                "OCR may misread names, amounts, URLs, or characters."
            ),
        )
