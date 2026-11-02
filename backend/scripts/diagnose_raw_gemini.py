import asyncio
import sys
import time
from typing import Any, Callable, Optional
import httpx

from google import genai
from google.genai import errors, types

from app.core.config import Settings, get_settings

# Diagnostic-only timeout in milliseconds
DIAGNOSTIC_TIMEOUT_MS = 60_000

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
    and 1 total attempt (0 retries). Bypasses FraudLens adapter logic.
    """
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=DIAGNOSTIC_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def create_content_config() -> types.GenerateContentConfig:
    """
    Constructs minimal generation config with store=False and tools disabled.
    Omits response_schema and structured output formatting.
    """
    return types.GenerateContentConfig(
        store=False,
        tools=None,
    )


async def run_diagnostic(
    settings: Optional[Settings] = None,
    client_factory: Optional[Callable[[str], genai.Client]] = None,
) -> int:
    """
    Executes a minimal, isolated Gemini API test using the official SDK directly.
    Bypasses FraudLens adapter and response validation.
    """
    sdk_version = getattr(genai, "__version__", "unknown")

    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            print("==================================================")
            print("FraudLens — Standalone Direct Gemini Diagnostic")
            print("==================================================")
            print(f"SDK Version:        {sdk_version}")
            print("--------------------------------------------------")
            print("Result:             CONFIGURATION_ERROR")
            print("Diagnostic Code:    CONFIGURATION_ERROR")
            print("Reason:             Failed to load application settings from backend/.env.")
            print("--------------------------------------------------")
            return 1

    if client_factory is None:
        client_factory = create_client

    print("==================================================")
    print("FraudLens — Standalone Direct Gemini Diagnostic")
    print("==================================================")
    print(f"SDK Version:        {sdk_version}")
    print(f"Model ID:           {settings.ai_model}")
    print(f"Configured Timeout: {DIAGNOSTIC_TIMEOUT_MS} ms")

    if not settings.is_ai_key_configured() or settings.ai_api_key is None:
        print("--------------------------------------------------")
        print("Result:             CONFIGURATION_ERROR")
        print("Diagnostic Code:    CONFIGURATION_ERROR")
        print("Reason:             AI_API_KEY is not configured or is a placeholder in backend/.env.")
        print("--------------------------------------------------")
        return 1

    api_key = settings.ai_api_key.get_secret_value().strip()

    client: Optional[genai.Client] = None
    start_time = time.perf_counter()
    exit_code = 1
    cleanup_exc: Optional[Exception] = None

    try:
        client = client_factory(api_key)
        config = create_content_config()

        # Fictional minimal prompt without response schema or JSON constraints
        prompt = "Reply with the word Hello."

        response = await client.aio.models.generate_content(
            model=settings.ai_model,
            contents=prompt,
            config=config,
        )

        elapsed = time.perf_counter() - start_time
        reply_text = getattr(response, "text", "") or ""
        sanitized_reply = reply_text.strip().replace("\r", " ").replace("\n", " ")

        if not sanitized_reply:
            print("--------------------------------------------------")
            print("Result:             FAILURE")
            print(f"Elapsed Time:       {elapsed:.2f}s")
            print("Diagnostic Code:    EMPTY_OR_INCOMPLETE_RESPONSE")
            print("Exception Class:    None")
            print("HTTP Status:        200")
            print("Provider Status:    None")
            print("--------------------------------------------------")
            exit_code = 1
        else:
            print("--------------------------------------------------")
            print("Result:             SUCCESS")
            print(f"Elapsed Time:       {elapsed:.2f}s")
            print(f"Harmless Reply:     {sanitized_reply}")
            print("--------------------------------------------------")
            exit_code = 0

    except errors.APIError as api_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(api_err).__name__
        http_code = getattr(api_err, "code", None)
        http_str = str(http_code) if http_code is not None else "None"
        prov_status = getattr(api_err, "status", None)
        prov_str = sanitize_provider_status(prov_status)

        print("--------------------------------------------------")
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Diagnostic Code:    PROVIDER_HTTP_ERROR")
        print(f"Exception Class:    {exc_class}")
        print(f"HTTP Status:        {http_str}")
        print(f"Provider Status:    {prov_str}")
        print("--------------------------------------------------")
        exit_code = 1

    except httpx.TimeoutException as timeout_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(timeout_err).__name__

        print("--------------------------------------------------")
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Diagnostic Code:    CLIENT_TIMEOUT")
        print(f"Exception Class:    {exc_class}")
        print("HTTP Status:        None")
        print("Provider Status:    None")
        print("--------------------------------------------------")
        exit_code = 1

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        exc_class = type(exc).__name__

        print("--------------------------------------------------")
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Diagnostic Code:    LOCAL_UNEXPECTED_ERROR")
        print(f"Exception Class:    {exc_class}")
        print("HTTP Status:        None")
        print("Provider Status:    None")
        print("--------------------------------------------------")
        exit_code = 1

    finally:
        if client is not None and hasattr(client, "aio") and hasattr(client.aio, "aclose"):
            try:
                await client.aio.aclose()
            except Exception as c_exc:
                cleanup_exc = c_exc

    if cleanup_exc is not None:
        c_class = type(cleanup_exc).__name__
        print(f"Cleanup Failure:    {c_class}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    code = asyncio.run(run_diagnostic())
    sys.exit(code)
