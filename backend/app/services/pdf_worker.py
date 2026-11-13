"""
Standalone PDF extraction worker process.
Executed as a separate OS process via:
  python -m app.services.pdf_worker <input_pdf_path> <output_json_path>

Guarantees:
- Runs in an isolated, independently terminable subprocess.
- Enforces an OS-level memory ceiling (256 MiB) on Windows via Windows Job Objects
  before untrusted PDF parsing starts.
- Pure-Python pypdf parsing: never executes JavaScript, never makes network calls.
- Enforces strict page bounds (<= 10 pages) and text limits (<= 10,000 characters).
- Enforces a strict output byte limit (<= 1 MiB) before writing JSON.
- Structured JSON output written to temporary output file; avoids unbounded pipe buffers.
"""
import ctypes
try:
    from ctypes import wintypes
except (ImportError, AttributeError):
    wintypes = None  # type: ignore

import json
import os
import sys
from typing import Any, Dict, List, Optional

MAX_DOCUMENT_PAGES = 10
MAX_EXTRACTED_CHARACTERS = 10_000
MAX_WORKER_RESULT_BYTES = 1024 * 1024  # 1 MiB worker JSON result ceiling
DEFAULT_MEMORY_LIMIT_MB = 256  # 256 MiB per-worker virtual memory limit

# Persistent module-level reference to keep Windows Job Object handle open for process lifetime
_job_handle: Optional[Any] = None


def apply_memory_limit_windows(limit_mb: int = DEFAULT_MEMORY_LIMIT_MB) -> bool:
    """
    Applies an OS-enforced virtual memory limit on Windows using Windows Job Objects.
    Applied strictly BEFORE untrusted PDF parsing begins.

    Mechanism:
    - Creates an anonymous Job Object via kernel32.CreateJobObjectW.
    - Configures JOBOBJECT_EXTENDED_LIMIT_INFORMATION with:
      JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
      ProcessMemoryLimit = limit_mb * 1024 * 1024
      JobMemoryLimit = limit_mb * 1024 * 1024
    - Assigns current process to the Job Object via AssignProcessToJobObject.

    Failure behavior:
    - If memory allocation exceeds the threshold, the OS rejects VirtualAlloc with
      ERROR_COMMITMENT_LIMIT, triggering a standard Python MemoryError.
    - MemoryError is caught and safely mapped to DOCUMENT_EXTRACTION_FAILED error JSON.
    - If unhandled or terminated by the OS, the process terminates non-zero, safely
      handled by the parent DocumentService.

    Platform Support:
    - Windows: Fully supported and enforced via Win32 Job Object API.
    - Non-Windows: Best-effort RLIMIT_AS on POSIX if available; Windows is the primary
      supported platform for this deployment target.
    """
    global _job_handle
    if sys.platform != "win32":
        # POSIX best effort if resource module is present
        try:
            import resource
            limit_bytes = limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
            return True
        except Exception:
            return False

    try:
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]

        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False

        limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_bytes = limit_mb * 1024 * 1024
        limit_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
        limit_info.ProcessMemoryLimit = limit_bytes
        limit_info.JobMemoryLimit = limit_bytes

        if not kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(limit_info),
            ctypes.sizeof(limit_info),
        ):
            return False

        if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
            return False

        _job_handle = job
        return True
    except Exception:
        return False


def normalize_page_text(raw_text: str) -> str:
    """
    Normalizes page text by stripping trailing whitespace per line
    while preserving meaningful line breaks and paragraph structure.
    """
    if not raw_text:
        return ""
    lines = [line.rstrip() for line in raw_text.splitlines()]
    return "\n".join(lines).strip()


def run_worker(input_pdf_path: str, output_json_path: str) -> None:
    # Apply OS-level memory ceiling BEFORE untrusted PDF parsing begins
    apply_memory_limit_windows(DEFAULT_MEMORY_LIMIT_MB)

    try:
        import pypdf
        import pypdf.errors
    except ImportError:
        write_error(
            output_json_path,
            code="DOCUMENT_EXTRACTION_FAILED",
            message="pypdf library is not installed or available in worker environment.",
            action="Ensure pypdf is installed in the backend Python virtual environment.",
        )
        return

    try:
        # Validate and open PDF
        try:
            reader = pypdf.PdfReader(input_pdf_path, strict=False)
        except pypdf.errors.FileNotDecryptedError:
            write_error(
                output_json_path,
                code="ENCRYPTED_PDF_REJECTED",
                message="Password-protected or encrypted PDFs are not supported.",
                action="Please upload an unencrypted text-based PDF.",
            )
            return
        except (pypdf.errors.PdfReadError, pypdf.errors.EmptyFileError):
            write_error(
                output_json_path,
                code="INVALID_PDF",
                message="Could not parse PDF. The file may be corrupt, damaged, or not a valid PDF.",
                action="Ensure the file is a valid, undamaged PDF document.",
            )
            return
        except Exception:
            write_error(
                output_json_path,
                code="INVALID_PDF",
                message="Could not parse PDF structure. The document is malformed or invalid.",
                action="Verify the file is an undamaged PDF document.",
            )
            return

        # Check encryption flag
        if getattr(reader, "is_encrypted", False):
            write_error(
                output_json_path,
                code="ENCRYPTED_PDF_REJECTED",
                message="Password-protected or encrypted PDFs are not supported.",
                action="Please upload an unencrypted text-based PDF.",
            )
            return

        # Page count bounds
        try:
            page_count = len(reader.pages)
        except Exception:
            write_error(
                output_json_path,
                code="INVALID_PDF",
                message="Could not enumerate pages in PDF document.",
                action="Ensure the document is a valid PDF.",
            )
            return

        if page_count == 0:
            write_error(
                output_json_path,
                code="INVALID_PDF",
                message="The PDF document contains 0 pages.",
                action="Ensure the PDF is a valid document containing pages.",
                page_count=0,
            )
            return

        if page_count > MAX_DOCUMENT_PAGES:
            write_error(
                output_json_path,
                code="PAGE_LIMIT_EXCEEDED",
                message=(
                    f"Document contains {page_count} pages, which exceeds the maximum limit "
                    f"of {MAX_DOCUMENT_PAGES} pages."
                ),
                action=f"Upload a PDF with {MAX_DOCUMENT_PAGES} or fewer pages.",
                page_count=page_count,
            )
            return

        # Page-by-page extraction
        page_infos: List[Dict[str, Any]] = []
        page_texts: List[str] = []
        cumulative_char_count = 0

        for page_idx in range(page_count):
            page_num = page_idx + 1
            try:
                page_obj = reader.pages[page_idx]
                raw_text = page_obj.extract_text() or ""
            except Exception:
                # If a single page fails text extraction, treat it as empty
                raw_text = ""

            cleaned_text = normalize_page_text(raw_text)
            has_text = bool(cleaned_text)
            page_char_count = len(cleaned_text)

            page_infos.append({
                "page_number": page_num,
                "has_text": has_text,
                "char_count": page_char_count,
            })

            if has_text:
                page_texts.append(cleaned_text)
                cumulative_char_count += page_char_count

                # Early check for character limit explosion
                if cumulative_char_count > MAX_EXTRACTED_CHARACTERS:
                    write_error(
                        output_json_path,
                        code="TEXT_TOO_LONG",
                        message=(
                            f"Extracted text exceeds the maximum limit of {MAX_EXTRACTED_CHARACTERS:,} "
                            f"characters ({cumulative_char_count:,} characters extracted so far)."
                        ),
                        action="Upload a shorter document excerpt or paste specific suspicious text directly.",
                        char_count=cumulative_char_count,
                    )
                    return

        # Combine text across pages using double newlines
        combined_text = "\n\n".join(page_texts).strip()
        total_chars = len(combined_text)

        if total_chars > MAX_EXTRACTED_CHARACTERS:
            write_error(
                output_json_path,
                code="TEXT_TOO_LONG",
                message=(
                    f"Extracted text exceeds the maximum limit of {MAX_EXTRACTED_CHARACTERS:,} "
                    f"characters ({total_chars:,} characters extracted)."
                ),
                action="Upload a shorter document excerpt or paste specific suspicious text directly.",
                char_count=total_chars,
            )
            return

        if not combined_text:
            write_error(
                output_json_path,
                code="EMPTY_DOCUMENT_EXTRACTION",
                message=(
                    "No usable text could be extracted from this PDF. Scanned PDFs, image-only "
                    "documents, and non-standard encodings are not supported."
                ),
                action=(
                    "Ensure the PDF contains embedded text rather than scanned images, or use "
                    "Screenshot Text Extraction for message images."
                ),
            )
            return

        # Check for partial empty pages
        empty_pages = [p["page_number"] for p in page_infos if not p["has_text"]]
        warning = None
        if empty_pages:
            warning = (
                f"Pages {', '.join(map(str, empty_pages))} contained no extractable text. "
                "Extraction may be incomplete. Note: Images, signatures, layout, and image-only "
                "text are not evaluated."
            )

        success_payload = {
            "status": "success",
            "combined_text": combined_text,
            "page_count": page_count,
            "char_count": total_chars,
            "extraction_method": "embedded_text",
            "empty_pages": empty_pages,
            "warning": warning,
            "pages": page_infos,
            "review_required": True,
            "notice": (
                "Analysis evaluates the submitted reviewed text only. Findings concern textual content, "
                "not document authenticity, signatures, visual tampering, sender identity, or URL reputation."
            ),
            "limitation": (
                "Extraction evaluates embedded text only. Images, signatures, layout, and image-only "
                "text are not evaluated."
            ),
        }

        # Enforce worker output byte limit before writing to disk
        json_bytes = json.dumps(success_payload, ensure_ascii=False).encode("utf-8")
        if len(json_bytes) > MAX_WORKER_RESULT_BYTES:
            write_error(
                output_json_path,
                code="DOCUMENT_EXTRACTION_FAILED",
                message="Worker extraction result exceeded the maximum allowed size limit (1 MiB).",
                action="Try uploading a shorter document or paste specific suspicious text directly.",
            )
            return

        with open(output_json_path, "wb") as f:
            f.write(json_bytes)

    except MemoryError:
        write_error(
            output_json_path,
            code="DOCUMENT_EXTRACTION_FAILED",
            message=f"Document extraction exceeded the maximum per-worker memory limit ({DEFAULT_MEMORY_LIMIT_MB} MiB).",
            action="Try uploading a smaller or less complex PDF document, or paste suspicious text directly.",
        )
    except Exception:
        write_error(
            output_json_path,
            code="DOCUMENT_EXTRACTION_FAILED",
            message="An unexpected error occurred while parsing the PDF document.",
            action="Try uploading a simpler PDF or copy and paste the text directly.",
        )


def write_error(
    output_json_path: str,
    code: str,
    message: str,
    action: str,
    page_count: Any = None,
    char_count: Any = None,
) -> None:
    payload = {
        "status": "error",
        "code": code,
        "message": message,
        "action": action,
    }
    if page_count is not None:
        payload["page_count"] = page_count
    if char_count is not None:
        payload["char_count"] = char_count

    try:
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(json_bytes) <= MAX_WORKER_RESULT_BYTES:
            with open(output_json_path, "wb") as f:
                f.write(json_bytes)
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    run_worker(sys.argv[1], sys.argv[2])
