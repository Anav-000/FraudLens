import asyncio
import sys
import time

from app.core.config import get_settings
from app.services.gemini import GeminiAdapter, GeminiAdapterError


async def main() -> int:
    settings = get_settings()

    print("==================================================")
    print("FraudLens — Synthetic Gemini Connectivity Verification")
    print("==================================================")
    print(f"Provider: {settings.ai_provider}")
    print(f"Model ID: {settings.ai_model}")

    adapter = GeminiAdapter(settings)
    start_time = time.perf_counter()

    try:
        greeting = await adapter.execute_synthetic_smoke_test()
        elapsed_seconds = time.perf_counter() - start_time

        script_detected = "Yes" if greeting.has_hindi_script() else "No (Devanagari script not detected)"

        print("--------------------------------------------------")
        print("Result: SUCCESS")
        print(f"Elapsed Time: {elapsed_seconds:.2f}s")
        print(f"Schema Validation: PASSED (Devanagari Script: {script_detected})")
        print("Harmless Synthetic Output:")
        print(f"  English: {greeting.english}")
        print(f"  Hindi:   {greeting.hindi}")
        print("--------------------------------------------------")
        print("Note: Hindi script detection confirms format presence, not translation quality.")
        print("Connectivity check complete. No user evidence was submitted or retained.")
        return 0

    except GeminiAdapterError as err:
        elapsed_seconds = time.perf_counter() - start_time
        http_str = str(err.http_status) if err.http_status is not None else "None (No HTTP response)"
        status_str = err.provider_status if err.provider_status is not None else "None (Not provided)"
        cleanup_str = (
            f"Warning - Secondary failure during cleanup ({err.cleanup_exception_class})"
            if err.cleanup_exception_class
            else "Clean (connections closed successfully)"
        )

        print("--------------------------------------------------")
        print("Result: FAILURE")
        print(f"Elapsed Time: {elapsed_seconds:.2f}s")
        print(f"Failure Stage: {err.stage}")
        print(f"Error Code: {err.code.value}")
        print(f"Exception Class: {err.exception_class}")
        print(f"HTTP Status: {http_str}")
        print(f"Provider Status: {status_str}")
        print(f"Message: {err.message}")
        print(f"Suggested Next Action: {err.action}")
        print(f"Cleanup Status: {cleanup_str}")
        print("--------------------------------------------------")
        return 1

    except Exception as unexpected:
        elapsed_seconds = time.perf_counter() - start_time
        print("--------------------------------------------------")
        print("Result: FAILURE")
        print(f"Elapsed Time: {elapsed_seconds:.2f}s")
        print("Failure Stage: unknown")
        print("Error Code: UNEXPECTED_LOCAL_ERROR")
        print(f"Exception Class: {type(unexpected).__name__}")
        print("HTTP Status: None (No HTTP response)")
        print("Provider Status: None (Not provided)")
        print("Message: An unhandled local exception occurred during script execution.")
        print("Suggested Next Action: Inspect local execution environment and Python dependencies.")
        print("Cleanup Status: Unknown")
        print("--------------------------------------------------")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
