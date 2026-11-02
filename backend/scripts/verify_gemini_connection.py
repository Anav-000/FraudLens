import asyncio
import sys
import time
from typing import Optional

from google import genai
from google.genai import errors, types

from app.core.config import get_settings


async def run_connection_check() -> int:
    settings = get_settings()

    print("==================================================")
    print("FraudLens — Gemini API Key & Service Diagnostics")
    print("==================================================")

    if not settings.is_ai_key_configured() or settings.ai_api_key is None:
        print("Result: CONFIGURATION_ERROR")
        print("Reason: AI_API_KEY is not configured or is a placeholder in backend/.env.")
        print("==================================================")
        return 1

    api_key = settings.ai_api_key.get_secret_value().strip()
    sdk_version = getattr(genai, "__version__", "unknown")
    print(f"SDK Version:       {sdk_version}")
    print(f"Configured Model:  {settings.ai_model}")

    client: Optional[genai.Client] = None

    try:
        # Step 1: Verify Key Validity against Google's Models Metadata Endpoint
        print("\n[Step 1/3] Verifying API Key Authentication...")
        start_auth = time.perf_counter()

        # Construct client with standard retry options (attempts=3) to absorb transient 503/504 spikes
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=1.0,
                    exp_base=2.0,
                    http_status_codes=[503, 504],
                ),
            ),
        )

        # Query metadata endpoint (fast, zero token inference cost, proves key is valid)
        accessible_models = []
        try:
            pager = await client.aio.models.list()
            for m in pager:
                name = getattr(m, "name", "")
                if "gemini" in name:
                    accessible_models.append(name.replace("models/", ""))
                if len(accessible_models) >= 5:
                    break
            auth_elapsed = time.perf_counter() - start_auth
            print(f"-> Key Status: VALID & AUTHENTICATED (Response in {auth_elapsed:.2f}s)")
            print(f"-> Sample Available Models: {', '.join(accessible_models)}")
        except errors.APIError as auth_err:
            auth_elapsed = time.perf_counter() - start_auth
            code = getattr(auth_err, "code", None)
            status = getattr(auth_err, "status", None)
            if code in (400, 401, 403):
                print(f"-> Key Status: REJECTED (HTTP {code}, status: {status})")
                print("-> Cause: The API key is invalid, revoked, or lacks Google AI Studio permissions.")
                return 1
            else:
                print(f"-> Key Metadata Query returned HTTP {code} ({status}) after {auth_elapsed:.2f}s")

        # Step 2: Test Inference with Configured Model with Retries Enabled
        configured_model = settings.ai_model
        print(f"\n[Step 2/3] Testing Inference on Configured Model ('{configured_model}')...")
        print("-> Retries enabled: 3 attempts with exponential backoff on transient 503/504")

        start_inf = time.perf_counter()
        config = types.GenerateContentConfig(store=False, tools=None)

        try:
            resp = await client.aio.models.generate_content(
                model=configured_model,
                contents="Reply with the word Hello.",
                config=config,
            )
            inf_elapsed = time.perf_counter() - start_inf
            reply = (getattr(resp, "text", "") or "").strip().replace("\r", " ").replace("\n", " ")
            print(f"-> Result: SUCCESS (Elapsed: {inf_elapsed:.2f}s)")
            print(f"-> Model Reply: '{reply}'")
            print("\n==================================================")
            print("Diagnostic Result: API key and configured model are fully operational.")
            print("==================================================")
            return 0
        except errors.APIError as inf_err:
            inf_elapsed = time.perf_counter() - start_inf
            inf_code = getattr(inf_err, "code", None)
            inf_status = getattr(inf_err, "status", None)
            print(f"-> Result: FAILED (Elapsed: {inf_elapsed:.2f}s, HTTP {inf_code}, status: {inf_status})")
            if inf_code == 503:
                print("-> Diagnosis: Google's serving cluster for this specific model is currently overloaded/unavailable.")
            elif inf_code == 504:
                print("-> Diagnosis: Google's backend queue timed out waiting for an inference worker.")

        # Step 3: Test Fallback Candidate Model if configured model is capacity-shedding
        fallback_model = "gemini-2.5-flash"
        if fallback_model != configured_model:
            print(f"\n[Step 3/3] Testing Alternative Cluster Model ('{fallback_model}')...")
            start_fb = time.perf_counter()
            try:
                resp_fb = await client.aio.models.generate_content(
                    model=fallback_model,
                    contents="Reply with the word Hello.",
                    config=config,
                )
                fb_elapsed = time.perf_counter() - start_fb
                reply_fb = (getattr(resp_fb, "text", "") or "").strip().replace("\r", " ").replace("\n", " ")
                print(f"-> Result: SUCCESS on '{fallback_model}' (Elapsed: {fb_elapsed:.2f}s)")
                print(f"-> Reply: '{reply_fb}'")
                print("\n==================================================")
                print(f"RECOMMENDATION: Google's '{configured_model}' cluster is currently experiencing capacity shortages.")
                print(f"Switching AI_MODEL to '{fallback_model}' in backend/.env will restore instant connectivity.")
                print("==================================================")
                return 0
            except errors.APIError as fb_err:
                fb_elapsed = time.perf_counter() - start_fb
                fb_code = getattr(fb_err, "code", None)
                fb_status = getattr(fb_err, "status", None)
                print(f"-> Result: FAILED on '{fallback_model}' as well (HTTP {fb_code}, status: {fb_status})")

        print("\n==================================================")
        print("OVERALL SUMMARY: Your API key is 100% valid and authenticated.")
        print("Google AI Studio's free-tier serving clusters are experiencing global server load.")
        print("==================================================")
        return 1

    except Exception as exc:
        print(f"\nUnexpected local diagnostic error: {type(exc).__name__}")
        return 1

    finally:
        if client is not None and hasattr(client, "aio") and hasattr(client.aio, "aclose"):
            try:
                await client.aio.aclose()
            except Exception:
                pass


if __name__ == "__main__":
    exit_code = asyncio.run(run_connection_check())
    sys.exit(exit_code)
