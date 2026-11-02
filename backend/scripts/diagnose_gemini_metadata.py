import asyncio
import sys
import time
from typing import Any, Callable, Optional
import httpx

from google import genai
from google.genai import errors, types

from app.core.config import Settings, get_settings

DIAGNOSTIC_TIMEOUT_MS = 60_000
OPERATION_NAME = "client.aio.models.get"

# Canonical Google/gRPC provider status codes allowlist
ALLOWED_PROVIDER_STATUSES = frozenset({
    "OK",
    "CANCELLED",
    "UNKNOWN",
    "INVALID_ARGUMENT",
    "DEADLINE_EXCEEDED",
    "NOT_FOUND",
    "ALREADY_EXISTS",
    "PERMISSION_DENIED",
    "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION",
    "ABORTED",
    "OUT_OF_RANGE",
    "UNIMPLEMENTED",
    "INTERNAL",
    "UNAVAILABLE",
    "DATA_LOSS",
    "UNAUTHENTICATED",
})


def sanitize_provider_status(val: Any) -> str:
    """Allowlist provider status codes; never print arbitrary strings."""
    if val is None:
        return "None"
    s = str(val).strip().upper()
    if s in ALLOWED_PROVIDER_STATUSES:
        return s
    return "None"


def create_client(api_key: str) -> genai.Client:
    """
    Constructs the official Google GenAI client directly with a 60s diagnostic timeout
    and 1 total attempt (0 retries).
    """
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=DIAGNOSTIC_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


async def run_diagnostic(
    settings: Optional[Settings] = None,
    client_factory: Optional[Callable[[str], genai.Client]] = None,
) -> int:
    """
    Executes a single model metadata lookup using client.aio.models.get.
    No generation request, model listing, pagination, or fallback.
    """
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            print("==================================================")
            print("FraudLens — Gemini Model Metadata Diagnostic")
            print("==================================================")
            print(f"Operation:          {OPERATION_NAME}")
            print("--------------------------------------------------")
            print("Result:             CONFIGURATION_ERROR")
            print("Diagnostic Code:    CONFIGURATION_ERROR")
            print("Reason:             Failed to load application settings from backend/.env.")
            print("Cleanup Status:     None (Client not initialized)")
            print("--------------------------------------------------")
            return 1

    if client_factory is None:
        client_factory = create_client

    print("==================================================")
    print("FraudLens — Gemini Model Metadata Diagnostic")
    print("==================================================")
    print(f"Operation:          {OPERATION_NAME}")
    print(f"Model ID:           {settings.ai_model}")
    print(f"Configured Timeout: {DIAGNOSTIC_TIMEOUT_MS} ms")

    if not settings.is_ai_key_configured() or settings.ai_api_key is None:
        print("--------------------------------------------------")
        print("Result:             CONFIGURATION_ERROR")
        print("Diagnostic Code:    CONFIGURATION_ERROR")
        print("Reason:             AI_API_KEY is not configured or is a placeholder in backend/.env.")
        print("Cleanup Status:     None (Client not initialized)")
        print("--------------------------------------------------")
        return 1

    api_key = settings.ai_api_key.get_secret_value().strip()

    client: Optional[genai.Client] = None
    start_time = time.perf_counter()
    exit_code = 1
    primary_failure: Optional[dict[str, str]] = None
    cleanup_exc: Optional[Exception] = None

    try:
        client = client_factory(api_key)

        # Single metadata query: client.aio.models.get(model=settings.ai_model)
        await client.aio.models.get(model=settings.ai_model)
        elapsed = time.perf_counter() - start_time
        exit_code = 0

    except errors.APIError as api_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(api_err).__name__
        http_code = getattr(api_err, "code", None)
        http_str = str(http_code) if http_code is not None else "None"
        prov_status = getattr(api_err, "status", None)
        prov_str = sanitize_provider_status(prov_status)

        primary_failure = {
            "elapsed": f"{elapsed:.2f}s",
            "diag_code": "PROVIDER_HTTP_ERROR",
            "exc_class": exc_class,
            "http_status": http_str,
            "prov_status": prov_str,
        }
        exit_code = 1

    except httpx.TimeoutException as timeout_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(timeout_err).__name__

        primary_failure = {
            "elapsed": f"{elapsed:.2f}s",
            "diag_code": "CLIENT_TIMEOUT",
            "exc_class": exc_class,
            "http_status": "None",
            "prov_status": "None",
        }
        exit_code = 1

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        exc_class = type(exc).__name__

        primary_failure = {
            "elapsed": f"{elapsed:.2f}s",
            "diag_code": "LOCAL_UNEXPECTED_ERROR",
            "exc_class": exc_class,
            "http_status": "None",
            "prov_status": "None",
        }
        exit_code = 1

    finally:
        if client is not None and hasattr(client, "aio") and hasattr(client.aio, "aclose"):
            try:
                await client.aio.aclose()
            except Exception as c_exc:
                cleanup_exc = c_exc

    cleanup_str = (
        f"Warning - Secondary failure during cleanup ({type(cleanup_exc).__name__})"
        if cleanup_exc is not None
        else "Clean"
    )

    print("--------------------------------------------------")
    if primary_failure is not None:
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {primary_failure['elapsed']}")
        print(f"Diagnostic Code:    {primary_failure['diag_code']}")
        print(f"Exception Class:    {primary_failure['exc_class']}")
        print(f"HTTP Status:        {primary_failure['http_status']}")
        print(f"Provider Status:    {primary_failure['prov_status']}")
        print(f"Cleanup Status:     {cleanup_str}")
        exit_code = 1
    elif cleanup_exc is not None:
        # Success on primary request, but cleanup failed
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Diagnostic Code:    CLEANUP_FAILURE")
        print("Exception Class:    None")
        print("Provider Status:    OK")
        print(f"Cleanup Status:     Cleanup Failure: {type(cleanup_exc).__name__}")
        exit_code = 1
    else:
        # Full success
        print("Result:             SUCCESS")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Provider Status:    OK")
        print("Cleanup Status:     Clean")
        exit_code = 0
    print("--------------------------------------------------")

    return exit_code


if __name__ == "__main__":
    code = asyncio.run(run_diagnostic())
    sys.exit(code)
