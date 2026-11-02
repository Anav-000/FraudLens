import sys
import time
from typing import Any, Callable, Optional
import httpx

from google import genai
from google.genai import errors, types
from google.genai._gaos.errors.genaierror import GenAiError
from google.genai._gaos.lib import compat_errors
from google.genai._gaos.utils.retries import RetryConfig

from app.core.config import Settings, get_settings

CONFIGURED_TIMEOUT_SECONDS = 60.0
CONFIGURED_TIMEOUT_MS = 60_000
API_METHOD_NAME = "client.interactions.create"
PROMPT = "Reply with the word Hello."
THINKING_LEVEL = "medium"

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


def create_configured_client(api_key: str) -> genai.Client:
    """
    Constructs official GenAI client and explicitly configures the Interactions
    subsystem for 60 seconds timeout and exactly one attempt (zero retries).
    Does not assume GenerateContent HttpOptions apply automatically to Interactions.
    Fails explicitly if required retry controls cannot be applied.
    """
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=CONFIGURED_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    # Explicitly enforce Interactions SDK configuration: 60s timeout, zero retries
    if not hasattr(client, "interactions") or not hasattr(client.interactions, "sdk_configuration"):
        try:
            client.close()
        except Exception:
            pass
        raise RuntimeError("Required retry controls could not be applied: Interactions subsystem or sdk_configuration is missing.")

    sdk_config = client.interactions.sdk_configuration
    sdk_config.timeout_ms = CONFIGURED_TIMEOUT_MS
    sdk_config.retry_config = RetryConfig(
        strategy="none",
        backoff=None,
        retry_connection_errors=False,
        max_retries=0,
    )

    return client


def extract_safe_text(interaction: Any) -> str:
    """
    Safely extracts text from an Interaction response object.
    Never prints interaction.steps[-1], raw step arrays, or full response objects.
    """
    output_text = getattr(interaction, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip().replace("\r", " ").replace("\n", " ")

    steps = getattr(interaction, "steps", None)
    if isinstance(steps, list):
        collected_parts = []
        for step in steps:
            if getattr(step, "type", None) == "model_output":
                content = getattr(step, "content", None)
                if isinstance(content, list):
                    for item in content:
                        if getattr(item, "type", None) == "text":
                            t = getattr(item, "text", "")
                            if isinstance(t, str) and t:
                                collected_parts.append(t)
        if collected_parts:
            return "".join(collected_parts).strip().replace("\r", " ").replace("\n", " ")

    return ""


def run_diagnostic(
    settings: Optional[Settings] = None,
    client_factory: Optional[Callable[[str], genai.Client]] = None,
) -> int:
    """
    Executes standalone diagnostic for Gemini 3.8 Flash using the Interactions API.
    Bypasses FraudLens application adapter and GenerateContent logic.
    """
    sdk_version = getattr(genai, "__version__", "unknown")

    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            print("==================================================")
            print("FraudLens — Standalone Gemini Interactions Diagnostic")
            print("==================================================")
            print(f"SDK Version:        {sdk_version}")
            print("--------------------------------------------------")
            print("Result:             CONFIGURATION_ERROR")
            print("Diagnostic Code:    CONFIGURATION_ERROR")
            print("Reason:             Failed to load application settings from backend/.env.")
            print("--------------------------------------------------")
            return 1

    if client_factory is None:
        client_factory = create_configured_client

    print("==================================================")
    print("FraudLens — Standalone Gemini Interactions Diagnostic")
    print("==================================================")
    print(f"SDK Version:        {sdk_version}")
    print(f"Model ID:           {settings.ai_model}")
    print(f"API Method:         {API_METHOD_NAME}")
    print(f"Configured Timeout: {CONFIGURED_TIMEOUT_MS} ms")

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

        # Call client.interactions.create with:
        # - model from settings
        # - input prompt
        # - store=False directly on request
        # - thinking_level="medium" in generation_config
        # - explicit timeout=60.0
        # - tools omitted completely (no Google Search or any other tool)
        interaction = client.interactions.create(
            model=settings.ai_model,
            input=PROMPT,
            store=False,
            generation_config={"thinking_level": THINKING_LEVEL},
            timeout=CONFIGURED_TIMEOUT_SECONDS,
        )

        elapsed = time.perf_counter() - start_time
        reply_text = extract_safe_text(interaction)

        if not reply_text:
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
            print(f"Harmless Reply:     {reply_text}")
            print("--------------------------------------------------")
            exit_code = 0

    except compat_errors.APITimeoutError as timeout_err:
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

    except compat_errors.APIError as compat_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(compat_err).__name__
        http_code = getattr(compat_err, "status_code", None)
        http_str = str(http_code) if http_code is not None else "None"

        # Safely extract structured provider status/code from body if available
        prov_candidate = None
        body = getattr(compat_err, "body", None)
        if isinstance(body, dict):
            err_data = body.get("error")
            if isinstance(err_data, dict):
                code_val = err_data.get("code") or err_data.get("status")
                if code_val and isinstance(code_val, (str, int)):
                    prov_candidate = str(code_val)
            elif isinstance(err_data, str) and err_data:
                prov_candidate = err_data
        elif hasattr(compat_err, "status"):
            prov_candidate = str(getattr(compat_err, "status"))

        prov_str = sanitize_provider_status(prov_candidate)

        print("--------------------------------------------------")
        print("Result:             FAILURE")
        print(f"Elapsed Time:       {elapsed:.2f}s")
        print("Diagnostic Code:    PROVIDER_HTTP_ERROR")
        print(f"Exception Class:    {exc_class}")
        print(f"HTTP Status:        {http_str}")
        print(f"Provider Status:    {prov_str}")
        print("--------------------------------------------------")
        exit_code = 1

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

    except GenAiError as gaos_err:
        elapsed = time.perf_counter() - start_time
        exc_class = type(gaos_err).__name__
        http_code = getattr(gaos_err, "status_code", None)
        http_str = str(http_code) if http_code is not None else "None"

        prov_candidate = None
        data = getattr(gaos_err, "data", None)
        if data is not None:
            err_obj = getattr(data, "error", None)
            if err_obj is not None:
                code_val = getattr(err_obj, "code", None)
                if code_val:
                    prov_candidate = str(code_val)

        prov_str = sanitize_provider_status(prov_candidate)

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
        if client is not None:
            try:
                client.close()
            except Exception as c_exc:
                cleanup_exc = c_exc

    if cleanup_exc is not None:
        c_class = type(cleanup_exc).__name__
        print(f"Cleanup Failure:    {c_class}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    code = run_diagnostic()
    sys.exit(code)
