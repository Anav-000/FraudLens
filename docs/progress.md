# FraudLens Development Progress

## Phase 2A: Gemini Integration Readiness

**Status**: Phase 2A Finalized & Live Verified  
**Milestone Completion Date**: 2026-10-29  

---

### 1. Completed Scope in Phase 2A

#### A. Official SDK & Model Selection
- Adopted the official **`google-genai` Python SDK** (`google-genai>=2.0.0,<3.0.0`, installed version `2.33.0`).
- **Final Selected Model**: `gemini-3.5-flash-lite`
  - *Models Documentation*: https://ai.google.dev/gemini-api/docs/models
  - *Structured Outputs Documentation*: https://ai.google.dev/gemini-api/docs/structured-output
  - *Dynamic Rate Limits Console*: https://aistudio.google.com/rate-limit
  - *Terms of Service*: https://ai.google.dev/gemini-api/terms
- **Historical Candidate & Investigation (`gemini-3.8-flash`)**:
  - The integration was initially prepared against `gemini-3.8-flash`.
  - Live smoke testing with `gemini-3.8-flash` returned HTTP 504 `DEADLINE_EXCEEDED` (~30s) and HTTP 503 `UNAVAILABLE` (6.29s) under `generate_content`, as well as client timeouts (~61s) under `interactions.create` across both Wi-Fi and mobile hotspot connections.
  - Standalone transport-level diagnostics confirmed that exactly 1 transport attempt was made in each scenario with zero unintended retries.
  - While AI Studio playground returned Hello, API gateway calls to `gemini-3.8-flash` consistently failed. The root cause remains **unknown / unconfirmed** (potential gateway queue delays, model provisioning latency, or capacity constraints on the free-tier developer endpoint).
  - Selected and configured **`gemini-3.5-flash-lite`**, which immediately succeeded in live testing.
  - Zero silent fallback: The application never switches models automatically; any model change is explicit via `AI_MODEL`.

#### B. User-Executed Live Verification Results
The user executed live out-of-band CLI verifications with their active Google AI Studio key:
1. **Direct Plain-Text Diagnostic (`scripts.diagnose_raw_gemini`)**:
   - **Result**: `SUCCESS`
   - **Elapsed Time**: `3.65s`
   - **Harmless Reply**: `Hello`
2. **Structured Greeting Smoke Test (`scripts.check_gemini`)**:
   - **Result**: `SUCCESS`
   - **Elapsed Time**: `1.80s`
   - **Schema Validation**: `PASSED`
   - **Bilingual Output**: Both English and Hindi greetings returned.
   - **Devanagari Detection**: `Yes` (Devanagari Unicode block `\u0900-\u097F` detected, confirming format presence).
   - **Evidence Privacy**: Zero user evidence submitted or retained.

#### C. Backend Configuration & Secret Hardening
- Reused `AI_PROVIDER`, `AI_MODEL`, and `AI_API_KEY` settings in `backend/app/core/config.py`.
- Preserved existing `ALLOWED_ORIGINS` comma-separated configuration format.
- Enforced `SecretStr` for `AI_API_KEY` to prevent accidental serialization, printing, or logging of credentials.
- Configured `.env` path resolution independent of the caller's working directory (`BACKEND_DIR / ".env"`), with environment variable precedence.
- Verified `backend/.env` is ignored by Git using `git check-ignore` (never committed or displayed).
- Missing, empty, or placeholder keys cleanly evaluate to `CONFIGURATION_MISSING`.

#### D. Isolated Gemini Adapter (`backend/app/services/gemini.py`)
- Single isolated module handling client creation and lifecycle cleanup via `await client.aio.aclose()`.
- Explicit timeout of 30 seconds (`types.HttpOptions(timeout=30_000)`).
- Zero automatic retries configured (`types.HttpRetryOptions(attempts=1)`).
- Explicitly disabled optional provider-side request storage (`store=False` in `GenerateContentConfig`).
- Explicitly disabled tools, search grounding, URL retrieval, file upload, or browsing (`tools=None`).
- Mapped all failure modes into safe application error categories:
  - `CONFIGURATION_MISSING`
  - `AUTH_FAILED`
  - `MODEL_UNAVAILABLE`
  - `QUOTA_EXCEEDED`
  - `NETWORK_TIMEOUT`
  - `PROVIDER_UNAVAILABLE`
  - `INVALID_RESPONSE`
- Strict exclusion: No request bodies, authorization headers, prompt texts, or raw exceptions are logged.
- Strictly isolated: No calls are triggered during server startup, health checks, capability checks, frontend load, or automated unit tests.

#### E. Capabilities & Quality Honesty
- **Separation of Concerns**: CLI verification (`check_gemini.py`) validates the Gemini API key, adapter configuration, and structured output parsing out-of-band.
- **Running Backend Status**: `GET /api/v1/capabilities` intentionally continues to report `ai_connection="not_tested"` at server runtime; it does not claim a live connection until live text analysis is active.
- **Honest Non-Implemented Response**: Text analysis remains intentionally unimplemented in this phase; `POST /api/v1/analyze/text` returns HTTP 501 `TEXT_ANALYSIS_NOT_IMPLEMENTED`.
- **Frontend UI Integrity**: The Analyze button remains explicitly disabled with clear explanatory text.

---

### 2. Actual Verification Results (Offline Test Suite)

| Suite | Scope | Target | Result | Status |
|---|---|---|---|---|
| **Backend Tests** | `pytest` | Health, Capabilities, 501 Honest Error, Validation Sanitization, Secret Protection, Input Limits, Gemini Configuration, Real SDK Config Construction, Error Mapping, Retry Disabling, Output Validation, Mock Transport Attempt Verification, Metadata Diagnostic | **68 passed, 0 failed** in 16.87s | **PASS** |
| **Frontend Tests** | `vitest` + RTL | Honest Capability Display, Backend Failure Handling, Recovery on Retry, Text Preservation across Retries, Language Toggle | **5 passed, 0 failed** in 1.50s | **PASS** |
| **Type Checking** | `tsc -b` | Strict TypeScript types across frontend components and API clients | **0 errors** | **PASS** |
| **Linting** | `eslint` | ESLint v9 with TypeScript and React Hooks rules | **0 errors, 0 warnings** | **PASS** |
| **Production Build** | `vite build` | Production bundle generation and minification | **Built in 1.55s** (157 kB JS, 14.8 kB CSS) | **PASS** |
| **Live Plain Diagnostic** | `diagnose_raw_gemini` | Manual user verification with Google AI Studio key (`gemini-3.5-flash-lite`) | **SUCCESS** (3.65s, Harmless reply returned) | **PASS** |
| **Live Smoke Test** | `check_gemini` | Manual user verification with Google AI Studio key (`gemini-3.5-flash-lite`) | **SUCCESS** (1.80s, Schema passed, Devanagari detected) | **PASS** |

---

### 3. Data Use & Privacy Clarifications (Free Tier)

- **Fictional Data Only**: On the Google AI Studio Free Tier, inputs and outputs may be processed by Google for service improvement and reviewed by human annotators under Google's Terms of Service. **Do not submit real, sensitive, or personally identifiable user evidence on the free tier.**
- **Storage Setting (`store=False`)**: The adapter sets `store=False` in `GenerateContentConfig` to opt out of developer-owned interaction logging in Google AI Studio project history where supported.
- **No Zero Retention Guarantee**: Setting `store=False` does **not** guarantee zero data retention and does not override Google's safety/abuse monitoring or free-tier service terms. Strict Zero Data Retention is an enterprise compliance feature available on Google Cloud Vertex AI, not the standard Gemini Developer API.

---

## Phase 2B: Suspicious Message Analysis

**Status**: Phase 2B Complete & Live Smoke Verified  
**Live Text Analysis Status**: SUCCESS (User-executed live smoke tests confirmed across English and Hindi scenarios)  
**Milestone Completion Date**: 2026-10-31  

---

### 1. Implemented Scope in Phase 2B

#### A. Structured Analysis Contract & Prompt Hardening
- **Schema**: Defined bounded Pydantic schemas in `backend/app/schemas/analysis.py`:
  - `AssessmentType`: `"warning_signs_found" | "no_clear_warning_signs" | "insufficient_information"`
  - `CategoryType`: `"job" | "phishing" | "shopping_payment" | "other" | "unclear"`
  - `WarningSign`: bounded `title` (max 100), `evidence_quote` (max 500), `explanation` (max 500).
  - `AnalysisModelOutput`: strict JSON schema (`extra="forbid"`) passed as Gemini `response_schema`.
  - `TextAnalysisResponse`: appends server metadata `analysis_basis="submitted_text_only"`, `external_checks_performed=False`, and explicit AI limitations.
- **Defensive Prompting & Injection Defense**:
  - Isolated untrusted message inside `<UNTRUSTED_MESSAGE>` tags.
  - Delivered rules via `types.GenerateContentConfig(system_instruction=...)` directing the model to evaluate text passively as evidence and ignore any system overrides or commands.
  - Disabled tools completely (`tools=None`).
  - Preserved `store=False` in `GenerateContentConfig`.
  - Configured temperature to 0.2 for reproducible analysis.

#### B. Evidence Grounding & Cross-Field Consistency
- **Verbatim Substring Grounding**:
  - Every `evidence_quote` returned by the model is validated against the submitted text using `quote in submitted_text`.
  - Rejects any hallucinated or fabricated quote immediately with `INVALID_RESPONSE` (HTTP 502).
- **Cross-Field Invariants**:
  - `warning_signs_found` requires at least 1 warning sign.
  - `no_clear_warning_signs` and `insufficient_information` forbid warning signs (length must be 0).
  - Language matching: The model output's `language` tag must match the requested language.

#### C. API Endpoint & Caching Policy
- Updated `POST /api/v1/analyze/text` in `backend/app/api/v1/analysis.py`.
- Replaced HTTP 501 stub with live execution of `adapter.analyze_message()`.
- Standardized error mapping: 503 (`AI_CONFIGURATION_MISSING`, `AI_AUTH_FAILED`, `AI_MODEL_UNAVAILABLE`, `AI_PROVIDER_UNAVAILABLE`), 429 (`AI_QUOTA_EXCEEDED`), 504 (`AI_NETWORK_TIMEOUT`, `AI_PROVIDER_DEADLINE_EXCEEDED`), 502 (`INVALID_AI_RESPONSE`), 500 (`INTERNAL_SERVER_ERROR`).
- Enforced `Cache-Control: no-store` header on all responses to prevent caching of submitted evidence.

#### D. Frontend Implementation & Safety Boundaries
- **Types & Client**: Created `TextAnalysisResponse` in `frontend/src/types/api.ts` and `analyzeText` API function in `frontend/src/lib/api.ts` with `AbortController` support and a 38-second client timeout (allowing backend 30s timeout to report cleanly).
- **AnalysisResultView (`frontend/src/features/analysis/AnalysisResultView.tsx`)**:
  - Distinct badges for `warning_signs_found`, `no_clear_warning_signs`, and `insufficient_information`.
  - **Prominent Disclaimer for Clean Findings**: Unmissable alert explaining that absence of warning signs does not prove legitimacy.
  - **Plain-Text URLs**: Quoted evidence containing URLs is formatted strictly as plain text in monospace blockquotes; never converted to clickable `<a>` links.
  - Executive summary in requested language.
  - Actionable verification steps and explicit uncertainties lists.
  - Provenance footer emphasizing submitted text basis only.
- **MessageAnalysisForm & App Integration**:
  - Analyze button enabled only when backend is connected, text analysis capability is true, AI key is configured, text is between 1 and 10,000 characters, and request is not in flight.
  - Duplicate click prevention during loading.
  - Spinner and status indicator without fake progress percentages.
  - Fictional data demo banner.
  - Preserves user text across errors; provides manual "Retry Analysis" button (zero auto-retries).
  - Clear / Reset button: clears text, clears findings, clears errors, and aborts any in-flight request via `AbortController`.
  - Stale detection: Changing text or switching language after receiving a result marks the result card as stale.

#### E. Safe Diagnostic Reason Codes & Error Reporting Fix (Phase 2B Hardening)
- **8 Safe Diagnostic Reason Codes**:
  - `EMPTY_RESPONSE`: Response was None, candidates list was empty, or content text was empty on completion.
  - `BLOCKED_RESPONSE`: Candidate finish_reason or prompt_feedback indicated safety filters, blocklist, or prohibited content.
  - `INCOMPLETE_RESPONSE`: Response was truncated specifically due to output token limits (`MAX_TOKENS`, `LENGTH`).
  - `UNSPECIFIED_FINISH_REASON`: Model generation terminated with an unspecified non-success finish reason (e.g. `OTHER`, `UNKNOWN`).
  - `SCHEMA_MISMATCH`: Generated output failed JSON parsing or Pydantic validation. Enforces strict schema contracts: arrays must be arrays, and `null` values for list fields produce `SCHEMA_MISMATCH` rather than being coerced. Records safe field paths and error types only (e.g. `loc (error_type)`), never raw text or input values.
  - `EVIDENCE_MISMATCH`: Warning sign cited an empty quote or a phrase not present as an exact verbatim substring in the submitted text (`quote in submitted_text`). Does not echo the quote or submitted text.
  - `LANGUAGE_MISMATCH`: Model returned declared language tag different from the requested language parameter (`output.language != requested_language`). Note: this checks declared field conformance against the request; it does not evaluate translation quality across all explanations.
  - `ASSESSMENT_INCONSISTENT`: Inconsistency between overall assessment verdict and warning sign counts.
- **Frontend Error Parsing Fix**:
  - Fixed client error parser in `frontend/src/lib/api.ts` to inspect top-level `{ code, reason, message, action }` rather than strictly nested `{ error: ... }` / `{ detail: ... }`.
  - Frontend now displays the backend's approved, sanitized error code, diagnostic reason code, and actionable advice instead of a generic "HTTP 502" message.
- **UI Copy Accuracy**:
  - Replaced stale "Phase 1 Foundation" badge with "Text Analysis Active".
  - Refined description to focus on text-message analysis.
  - Clearly marked screenshots, document extraction, and URL reputation checks as planned future capabilities not currently available.

#### F. Provider Request Rejection Resolution & Schema Separation
- **Diagnostic Findings & Root Cause**:
  - Inspecting the serialized request payload sent over the wire revealed that Pydantic models configured with `model_config = ConfigDict(extra="forbid")` automatically generated `additionalProperties: false` in the JSON schema.
  - While Google Vertex AI Enterprise Agent Platform supports `additionalProperties`, the Google Gemini Developer API (`v1beta`) REST schema endpoint strictly rejects `additionalProperties` / `additional_properties` with HTTP 400 `INVALID_ARGUMENT`.
  - In contrast, the successful `SyntheticGreetingResponse` smoke test lacked `extra="forbid"`, producing a standard OpenAPI subset without `additional_properties`.
- **Architectural Separation**:
  - **Provider-Facing Schema (`AnalysisProviderOutputSchema`)**: Clean, standard OpenAPI schema subset without `extra="forbid"` or Pydantic `default_factory` in wire definitions. Ensures zero unsupported schema keywords are sent over the wire.
  - **Application-Side Validation Schema (`AnalysisModelOutput`)**: Retains full, strict application validation including `model_config = ConfigDict(extra="forbid")`, local string length bounds, list item bounds, verbatim quote substring verification, and cross-field invariants.
- **Error Category Separation**:
  - Distinctly separated **Provider Request Rejection** (`AI_REQUEST_REJECTED`, HTTP 502) from **Generated Output Validation Failure** (`INVALID_AI_RESPONSE` / `SCHEMA_MISMATCH`, HTTP 502).
  - Implemented safe structured provider field violation extraction (`_extract_safe_field_violations`) that extracts allowlisted configuration field paths (e.g. `generation_config.response_schema.additional_properties`) while strictly discarding raw error messages, descriptions, headers, and prompt texts.

#### G. Instruction Calibration & UI Category Refinement
- **Frontend Category Label**: Renamed category label `"other"` from “Other Suspicious Pattern” to “Other / General Message” in `AnalysisResultView.tsx`, while maintaining the backend API enum value `"other"` unchanged.
- **Strengthened Trusted Instructions (`_build_analysis_prompt`)**:
  - Grounded claims: Directed the model to report strictly observations supported by the submitted text.
  - Domain claims: Prohibited claiming a URL differs from an organization's verified official domain when no independent domain verification took place.
  - URL descriptions: Directed the model to describe suspicious URL patterns as textual observations while stating that domain ownership and registration authenticity have not been verified.
  - Calibrated benign findings: Directed the model to use calibrated wording (e.g. “appears to be”, “no clear warning signs identified in the submitted text”) rather than asserting definitive legitimacy.
  - Preserved verbatim quotes: Reaffirmed that evidence quotes must remain exact source-language substrings even when explanations are generated in Hindi.

#### H. User-Executed Manual Smoke Verification Results
The user completed live manual smoke verifications with their configured Google AI Studio key:
1. **Advance-Fee Job Offer (English)**: Successfully flagged with `warning_signs_found`, categorized under Job/Employment, and cited exact verbatim quotes for the upfront registration fee.
2. **Account Suspension Phishing (Hindi)**: Produced structured Hindi explanations and advice while citing the exact source English text for the quoted evidence.
3. **Routine Meeting Reminder (English)**: Returned `no_clear_warning_signs` along with the prominent caution alert clarifying that absence of detected signs does not prove sender authenticity.
4. **Input Modification (Stale State)**: Editing message text after completion visibly marked existing results as stale with a warning callout.
5. **Clear / Reset**: Cleared input text, findings, and error states, safely returning the form to its initial ready state with the Analyze button disabled until text is re-entered.

*Scope Clarification*: These user checks serve as limited smoke tests confirming end-to-end integration, bilingual rendering, and UI state transitions. They do not constitute an empirical accuracy benchmark or adversarial robustness evaluation. Client-side abort signal handling and URL non-clickability were verified via automated unit and component test suites.

---

### 2. Verification Results (Phase 2B Offline Suite)

| Suite | Scope | Target | Result | Status |
|---|---|---|---|---|
| **Backend Tests** | `pytest` | 98 tests: Health, Capabilities, Analysis routing, Validation Sanitization, Secret Non-disclosure, Gemini Client Creation, Timeout/Retry Disabling, Evidence Substring Validation, 8 Safe Output Diagnostic Codes (`EMPTY_RESPONSE`, `BLOCKED_RESPONSE`, `INCOMPLETE_RESPONSE`, `UNSPECIFIED_FINISH_REASON`, `SCHEMA_MISMATCH`, `EVIDENCE_MISMATCH`, `LANGUAGE_MISMATCH`, `ASSESSMENT_INCONSISTENT`), Provider Request Rejection (`AI_REQUEST_REJECTED`), Safe Field Violation Extraction, Wire Serialized Schema Shape Verification (Zero `additionalProperties`), Cross-field Invariants, Strict Array Validation (Null List Rejection), Language Matching, Prompt Injection Defense, Error Mapping, Diagnostics | **98 passed, 0 failed** in 16.34s | **PASS** |
| **Frontend Tests** | `vitest` + RTL | 25 tests across 3 suites: API Client error parsing (code, reason, message, action on 502, `AI_REQUEST_REJECTED`, non-JSON fallback, abort signal), Capability Status, Backend Unavailable, Connection Retry, Text Preservation, Language Toggle, Analyze Button Enable/Disable on AI Config, Submission & Findings Rendering, Category Labeling ("Other / General Message"), Quoted URLs as Plain Text (no links), Clean Finding Disclaimer, Stale Detection on Input Change, Clear/Reset & Abort Handling, Error Banner with `AI_REQUEST_REJECTED` & `INVALID_AI_RESPONSE` Reason Codes, Header copy & planned labels | **25 passed, 0 failed** in 36.33s | **PASS** |
| **Type Checking** | `tsc -p tsconfig.json` | Strict TypeScript types across all components, API client, and tests | **0 errors** | **PASS** |
| **Linting** | `eslint .` | ESLint v9 with strict TypeScript and React Hooks rules | **0 errors, 0 warnings** | **PASS** |
| **Production Build** | `vite build` | Production bundle generation and minification | **Built in 2.75s** (169.2 kB JS, 18.0 kB CSS) | **PASS** |
| **Live Smoke Verification** | Manual | Fictional scenarios (Job fee, Hindi phishing, Routine meeting, Stale state, Reset) executed by user | **Confirmed by user** | **PASS** |

---

### 3. Next Milestone: Phase 3

---

## Phase 3A: Screenshot Text Extraction and Review

**Status**: Phase 3A Complete, Windows Uvicorn Reload Bug Fixed & Verified  
**Milestone Completion Date**: 2026-11-02  
**Host Prerequisite Status**: Tesseract-OCR v5.5.0 installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` (`eng`, `hin`, `osd`). `screenshot_extraction: true` active.

---

### 1. Completed Scope in Phase 3A

#### A. Local OCR Architecture & Engine
- **Engine**: Local Tesseract OCR via subprocess invocation with Pillow (`PIL`) image validation and preprocessing.
- **Privacy Boundary**: Screenshot processing runs **100% locally on the backend**. The screenshot image is **never** sent to Google Gemini or any external cloud OCR API.
- **Language Separation**:
  - `ocr_language`: Controls optical character recognition of the image (`"eng"` for English, `"hin"` for Hindi).
  - `language`: Controls downstream Gemini AI analysis explanation output (`"en"` or `"hi"`).
- **Subprocess Execution & Dual Event Loop Compatibility**:
  - Handles both Windows `ProactorEventLoop` and `_WindowsSelectorEventLoop` (the default event loop chosen by Uvicorn when running in `--reload` or multi-worker mode on Windows).
  - Uses `asyncio.to_thread` with a dedicated synchronous runner `_run_tesseract_process_sync` when running on `SelectorEventLoop` (or as a fallback if `create_subprocess_exec` raises `NotImplementedError`).
  - Bounded concurrency with `asyncio.Semaphore(3)` protects server CPU resources.
  - Enforces a strict 20.0-second execution timeout.
  - Timeout and cancellation handlers terminate child processes immediately via `proc.kill()` and reap them via `proc.wait()`.
- **Strict Image Validation & Security Limits**:
  - **Allowed formats**: Strictly PNG and JPEG (`ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG"}`). Formats are validated against decoded Pillow image headers, rejecting extension/MIME spoofing.
  - **File size limit**: 5 MiB (`5 * 1024 * 1024` bytes). Ingested using 64 KiB streaming chunks; uploads exceeding 5 MiB are terminated immediately with HTTP 413 `FILE_TOO_LARGE`.
  - **Decoded image limit**: 12 megapixels (`12,000,000` pixels). Pillow `Image.MAX_IMAGE_PIXELS` and explicit dimension checks prevent decompression-bomb attacks (`IMAGE_TOO_LARGE`).
  - **Static images only**: Animated GIF, multi-frame TIFF, and APNG files are rejected with HTTP 422 `ANIMATED_IMAGE_REJECTED`.
  - **Orientation normalization**: `ImageOps.exif_transpose` normalizes smartphone EXIF orientation so rotated screenshot text is read upright.
- **Resource Cleanup & Zero Persistence**:
  - Images are processed in memory (`io.BytesIO`).
  - Temporary files generated for the Tesseract CLI are written to secure temporary locations and unconditionally unlinked in `finally:` blocks on success, failure, or timeout.
  - Zero persistent screenshot storage, database records, analytics payloads, or image logging.
  - `Cache-Control: no-store` header is enforced on all extraction responses and error payloads.
- **Character Limit Enforcement**:
  - Extracted text is normalized and checked against the 10,000-character limit.
  - Text exceeding 10,000 characters is rejected with HTTP 422 `TEXT_TOO_LONG` advising the user to crop the screenshot.
  - Empty or whitespace-only extractions return HTTP 422 `EMPTY_EXTRACTION` with helpful guidance.

#### B. Truthful Capabilities Reporting
- `GET /api/v1/capabilities` dynamically checks whether `tesseract.exe` is present on PATH or standard Windows installation locations via `check_ocr_availability()`.
- When Tesseract is installed with English and Hindi, capabilities returns:
  ```json
  {
    "text_analysis": true,
    "screenshot_extraction": true,
    "ocr_languages": ["eng", "hin"],
    "ocr_prerequisite_status": "ready"
  }
  ```
- Missing OCR prerequisites do **not** disable working text analysis.

#### C. Frontend Human-in-the-Loop Review Workflow
- **`ScreenshotExtractor` Component**:
  - Accessible file dropzone and picker accepting `.png`, `.jpg`, `.jpeg` ($\le 5$ MiB).
  - Client-side size and format pre-validation.
  - Local preview thumbnail using object URLs with automatic cleanup via `URL.revokeObjectURL` on file change, reset, or component unmount.
  - OCR language selection (`EN (eng)` / `HI (hin)`).
  - Honest status banner when OCR engine is unavailable on the backend host.
  - Loading state with duplicate-submission protection and `AbortController` cancellation.
  - **Editable Review Area**:
    - Extracted text is presented in an editable textarea for user correction.
    - Prominent warning: *"OCR may misread names, amounts, URLs, or characters. Please review and correct the text below before confirming for analysis."*
    - Explicit confirmation checkbox: `[ ] I have reviewed and confirmed the extracted text for accuracy.`
    - **Review Invalidation**: Modifying the reviewed text automatically unchecks the confirmation checkbox, requiring re-confirmation before analysis transfer.
    - Replacing or removing the screenshot invalidates the prior extraction and revokes the preview URL.
  - **Analysis Transfer & Provenance**:
    - Clicking "Use Reviewed Text for Analysis" populates the message analysis form and displays a clear provenance badge:
      > *"Screenshot Text Provenance Notice: Analysis evaluates the submitted reviewed text only. Findings concern textual content, not image authenticity, visual tampering, sender identity, or URL reputation."*
    - Downstream analysis reuses `POST /api/v1/analyze/text`, preserving exact evidence substring validation, calibrated instructions, and privacy guarantees.

---

### 2. Investigation & Fix: Windows Uvicorn Reload `OCR_EXECUTION_FAILED`

#### A. Problem Statement
When running the backend server on Windows using the development reload command:
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Attempting screenshot extraction in the browser resulted in HTTP 500 with:
```json
{
  "code": "OCR_EXECUTION_FAILED",
  "reason": "OCR_EXECUTION_ERROR",
  "message": "An error occurred while executing optical character recognition."
}
```
Meanwhile, direct execution in PowerShell of the exact same image through `tesseract.exe` succeeded immediately:
```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" "C:\Users\HP\Pictures\Screenshots\Screenshot 2026-11-02 152123.png" stdout -l eng
```

#### B. Root Cause Identification
1. **Failing Stage**: Subprocess pipe creation inside `_execute_tesseract_subprocess` at `asyncio.create_subprocess_exec`.
2. **Exception Class**: `builtins.NotImplementedError` raised by `asyncio.base_events.BaseEventLoop._make_subprocess_transport`.
3. **Trigger Mechanism**:
   - In Uvicorn, specifying `--reload` sets `uvicorn.Config.use_subprocess = True`.
   - In `uvicorn.loops.asyncio.asyncio_loop_factory`, when `sys.platform == "win32"` and `use_subprocess is True`, Uvicorn explicitly initializes `asyncio.SelectorEventLoop` (`_WindowsSelectorEventLoop`) rather than Python 3.8+'s default `_WindowsProactorEventLoop`.
   - On Windows, `SelectorEventLoop` does not implement asynchronous subprocess transports, raising `NotImplementedError` whenever `asyncio.create_subprocess_exec` is called.
   - The broad `except Exception:` block previously caught `NotImplementedError` and raised generic `OcrExecutionError`, producing HTTP 500 `OCR_EXECUTION_FAILED`.

#### C. Solution Implemented
1. **Thread-Based Subprocess Fallback**:
   - Added `_run_tesseract_process_sync(tesseract_cmd, image_path, ocr_language, timeout, proc_holder)` executing `subprocess.Popen` in a worker thread via `asyncio.to_thread`.
   - Detected `SelectorEventLoop` explicitly on Windows and handled `NotImplementedError` fallthrough on custom loops.
2. **Process Termination & Reaping Guarantee**:
   - Thread runner records the active `subprocess.Popen` in a thread-safe `proc_holder` list.
   - If `asyncio.wait_for` triggers a timeout or cancellation, the process is terminated (`proc.kill()`) and reaped (`proc.wait()`), preventing zombie or orphaned processes.
3. **Safe Diagnostic Codes**:
   - Differentiated failure modes with sanitized reason codes: `SUBPROCESS_NONZERO_EXIT`, `SUBPROCESS_TIMEOUT`, and `SUBPROCESS_EXECUTION_ERROR`.
   - Preserved strict confidentiality: internal file paths, stderr details, and raw OCR outputs are never leaked in error payloads.

#### D. Real HTTP Local OCR Verification
Tested `POST /api/v1/extract/screenshot` on the real fictional screenshot (`C:\Users\HP\Pictures\Screenshots\Screenshot 2026-11-02 152123.png`) under the `_WindowsSelectorEventLoop`:
- **HTTP Status**: 200 OK
- **Cache-Control**: `no-store`
- **Extracted Character Count**: 152 characters
- **Extracted Text Output**:
  ```text
  Congratulations! You have been selected for a remote job.
  Pay a refundable registration deposit of Rs 1500 today.
  Contact: registration@example. invalid
  ```

---

### 3. Offline Robustness Review & Hardening

#### A. Subprocess Lifecycle Hardening (`_SyncOcrRunner`)
- **Race Condition Immunity**:
  - Implemented `_SyncOcrRunner` with strict lock-based state management (`threading.Lock` and `threading.Event`).
  - **Cancellation before process creation**: If the task is cancelled before `subprocess.Popen` is invoked, `CancelledError` is raised immediately and no process is ever spawned.
  - **Cancellation during process creation**: If `cancel()` is triggered during `Popen`, the lock guarantees the process reference is captured and immediately killed.
  - **Cancellation or timeout during execution**: When `asyncio.wait_for` triggers a timeout or cancellation, `runner.cancel()` kills the process, and `_terminate_and_reap()` reaps the child process via `proc.wait()`.
- **Non-blocking Event Loop Reaping**:
  - All synchronous process wait and reap calls (`proc.wait()`) execute inside the worker thread pool.
  - The main asyncio event loop awaits the worker task nonblockingly via `await worker_task`.
  - Concurrency slots (`_ocr_semaphore`) and temporary file handles remain strictly owned until after the worker thread has completely finished process reaping.
  - Tested deterministically for all races, including task cancellation while waiting for a concurrency slot.

#### B. Upload Limits Before Multipart Spooling
- **Pre-Spool Request Bounding (`BoundedUploadMiddleware`)**:
  - A size check on `UploadFile` after parsing is insufficient because Starlette's multipart parser spools oversized uploads to disk before endpoint invocation.
  - Implemented ASGI middleware `BoundedUploadMiddleware` protecting `/api/v1/extract/screenshot`.
  - **Documented Overhead Buffer**: Configured `MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024` (5 MiB) with `MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024` (64 KiB), establishing a strict body limit of 5,308,416 bytes (~5.06 MiB).
  - **Explicit `Content-Length` Check**: Any request declaring `Content-Length > 5,308,416` is rejected with HTTP 413 `FILE_TOO_LARGE` immediately without reading or spooling a single byte.
  - **Streamed / Chunked Tracking**: For requests with missing, chunked, or misleading `Content-Length`, incoming ASGI chunks are summed. If cumulative bytes exceed the limit, streaming is aborted immediately with HTTP 413 `FILE_TOO_LARGE`.
  - **Excess Multipart Parts & Multiple Files**:
    - Registered `StarletteHTTPException` handler mapping multipart part boundary errors (> 1000 fields) to HTTP 400 `INVALID_MULTIPART_REQUEST` with `Cache-Control: no-store`.
    - Enforced strict part constraints: multipart payload must contain only `file` and optional `ocr_language`. Rejects unexpected fields with HTTP 422 `UNEXPECTED_MULTIPART_FIELDS`.
    - Rejects multiple files with HTTP 422 `MULTIPLE_FILES_REJECTED`.
    - Guaranteed cleanup: all file handles are closed and unlinked on rejection.

#### C. Human-in-the-Loop Review, Stale-State, and Isolation
- **OCR Transcription Errors as Review Rationale**:
  - Optical character recognition engines can misread subtle characters (e.g. `1` vs `l`, `0` vs `O`), monetary amounts, phone numbers, punctuation, Hindi Devanagari matras, or deceptive phishing domain homoglyphs.
  - **Exact Evidence Substring Grounding**: FraudLens's downstream analysis validates verbatim substring quotes against the *submitted reviewed text*, **not** the raw pixels of the screenshot image.
  - Mandatory review gives users an opportunity to identify and correct transcription errors; errors may remain after confirmation.
- **Review Confirmation & Stale State Rules**:
  - Editing reviewed OCR text immediately unchecks the review confirmation checkbox and disables the transfer button.
  - Changing OCR language or replacing the selected screenshot clears prior extractions, revokes object URLs, and invalidates review confirmation, preventing obsolete extractions from being transferred.
  - Transferring reviewed text into the main analysis form marks any previously rendered analysis result as stale (`isResultStale = true`).
  - Manual text edits in the analysis form are preserved across state transitions.
  - **Outbound AI Isolation**: Extraction and transfer operations **never** call Google Gemini or external services. Downstream analysis requires an explicit user click on "Analyze Message".

#### D. Manual Smoke Test Record (Qualitative Observations Only)
User-executed manual checks confirmed:
1. **English Screenshot Flow**: Screenshot upload, local backend extraction, user text correction, review confirmation, transfer to analysis form, and explicit analysis execution succeeded.
2. **Hindi Screenshot Flow**: Hindi screenshot upload, Hindi OCR (`hin`), text correction, review confirmation, transfer, and subsequent analysis succeeded.
3. **Bilingual Grounding**: English explanations properly preserved Hindi source-language evidence quotes without translation errors or quote mismatch.
*Scope Notice*: These observations are recorded strictly as qualitative smoke checks demonstrating UI state flow and bilingual rendering, not as an empirical accuracy benchmark or adversarial evaluation.

---

## Phase 3B: Text-Based PDF Document Extraction

**Status**: Phase 3B Complete & Verified  
**Milestone Completion Date**: 2026-11-03  

### 1. Scope & Implementation Overview

#### A. Local PDF Text Extraction Architecture
- **Library Selection**: Adopted **`pypdf`** (`pypdf>=5.0.0,<6.0.0`, version 5.9.0, BSD-3-Clause license). Maintained pure-Python library with zero native compilation dependencies.
- **Privacy Boundary**: Document parsing runs **100% locally on the backend server**. The PDF document is **never** sent to Google Gemini or external services.
- **Isolated Worker Process Execution**:
  - Untrusted PDF parsing runs in an independent child process (`app.services.pdf_worker`) managed by `_SyncDocumentRunner`.
  - Guarantees: Timeouts (20.0s) and cancellations forcibly kill the worker process (`proc.kill()`) and reap it via `proc.wait()`.
  - Non-blocking `cancel()` does not stall the asyncio event loop on Windows with Uvicorn `--reload`.
  - Shielded cleanup ensures the worker process is completely reaped before releasing the concurrency slot or unlinking temporary files.
  - Concurrency: Document extraction uses `_document_semaphore = asyncio.Semaphore(3)`, operating independently from OCR's `_ocr_semaphore = asyncio.Semaphore(3)`. Up to 3 OCR workers and 3 PDF workers (up to 6 extraction subprocesses total) can execute concurrently.
- **Resource Limits & Memory Defense**:
  - **File Size**: 5 MiB maximum (`5 * 1024 * 1024` bytes). Pre-spool bounded upload middleware rejects oversized uploads before disk spooling.
  - **Document Length**: 10 pages maximum (`MAX_DOCUMENT_PAGES = 10`). Documents exceeding 10 pages are rejected with HTTP 422 `PAGE_LIMIT_EXCEEDED` (never silently truncated).
  - **Extracted Text Limit**: 10,000 characters maximum (`MAX_EXTRACTED_CHARACTERS = 10_000`). Exceeding text is rejected with HTTP 422 `TEXT_TOO_LONG`.
  - **Enforceable Memory Limit**: Windows Job Objects enforce a 256 MiB virtual memory ceiling per worker process on Windows before untrusted PDF parsing starts. Exceeding this triggers `MemoryError` safely mapped to `DOCUMENT_EXTRACTION_FAILED`. Best-effort RLIMIT_AS applies on POSIX if available.
  - **Bounded I/O & Output Size**: Child `stdout` and `stderr` are discarded via `subprocess.DEVNULL`. Worker output JSON is checked and restricted to $\le 1$ MiB (`MAX_WORKER_RESULT_BYTES = 1024 * 1024`) both before worker write and before parent read/decode.
  - **Security Restrictions**: Pure-Python reader does not execute PDF JavaScript, does not open embedded file attachments, does not follow external links/URIs, and does not render visual raster graphics.
  - **Encryption**: Encrypted / password-protected PDFs are rejected with safe, actionable error `ENCRYPTED_PDF_REJECTED` (HTTP 422). Passwords are not accepted in this phase.
- **Handling Pages Without Extractable Text**:
  - If the entire document has no usable text: rejected with HTTP 422 `EMPTY_DOCUMENT_EXTRACTION`, explaining that scanned or image-only PDFs are not supported.
  - If only some pages have no text: returns structured page information, collects `empty_pages`, and includes a calibrated warning that extraction may be incomplete. Does not claim every empty page is necessarily scanned.

#### B. Frontend Document Extraction & Review Workflow
- **`DocumentExtractor` Component**:
  - PDF-only file dropzone and picker accepting `.pdf` / `application/pdf`.
  - Displays plain-text filename and human-readable file size.
  - Prominent limit notice: Max 5 MiB, Max 10 pages.
  - Explicit "Extract Text" button with loading spinner and cancellation support.
  - Incomplete extraction warning banner identifying empty page numbers.
  - Editable review textarea with character counter.
  - Review explanation notice:
    > *"Extraction can alter reading order, spacing, and characters, and may omit content. Confirmation is an opportunity to correct errors, not a guarantee of accuracy."*
  - Local privacy notice explaining that the PDF stays on the backend and only reviewed text is sent to the AI provider upon Analyze.
  - Review confirmation checkbox: `[ ] I have reviewed and confirmed the extracted text for accuracy.`
  - Invalidation on edit: modifying textarea unchecks confirmation immediately (`userHasEditedRef` guard prevents late responses from overwriting user edits).
  - Explicit confirmation before replacing nonempty analysis input: shows prompt asking user to confirm before overwriting existing message text.
  - Document text provenance notice displayed on analysis form:
    > *"Document Text Provenance Notice: Analysis evaluates the submitted reviewed text only. Findings concern textual content, not document authenticity, signatures, visual tampering, sender identity, or URL reputation."*

---

### 2. Actual Verification Results (Phase 3B Final)

| Suite | Scope | Target | Result | Status |
|---|---|---|---|---|
| **Backend Tests** | `pytest` | 167 tests across 8 test files: Health, Capabilities, Text Analysis, Gemini Adapter, Diagnostics, OCR Preprocessing, Dual Event Loops, Non-blocking Cancellation, Streamed Multipart Oversize Abort, Spool Cleanup, Excess Parts, Document Service & Worker (Single-page, Multipage, Hindi Unicode UTF-16BE, Empty doc, Mixed pages, Corrupt PDF, Encrypted PDF, 10-page limit, 10,000-char limit, Worker timeout termination, Reaping, Concurrency slot ownership, Delayed worker creation responsiveness, Repeated cancellation shielding, Outbound network isolation) | **167 passed, 0 failed** in 20.65s | **PASS** |
| **Frontend Tests** | `vitest` | 49 tests across 5 test suites: API Client (`extractDocument`), `DocumentExtractor` (PDF drop, validation, size check, format check, incomplete extraction warning, review confirmation gating, edit invalidation, late response discard, nonempty input replace confirmation), `ScreenshotExtractor`, `AnalysisResultView`, `App` Integration (Document text transfer, Document provenance notice, stale-state marking, zero AI calls during transfer) | **49 passed, 0 failed** in 19.70s | **PASS** |
| **Type Checking** | `tsc -b` | Strict TypeScript compilation across all frontend components, types, and tests | **0 errors** | **PASS** |
| **Linting** | `eslint .` | ESLint v9 with strict TypeScript and React Hooks rules | **0 errors, 0 warnings** | **PASS** |
| **Production Build** | `vite build` | Production bundle generation and minification | **Built in 2.18s** (195.56 kB JS, 23.55 kB CSS) | **PASS** |
| **Real Local HTTP PDF Extraction** | HTTP Endpoint | Synthetic fixture `job_offer_notice.pdf` through `POST /api/v1/extract/document` | **HTTP 200 OK**: Extracted 161 characters, `Cache-Control: no-store` | **PASS** |

---

### 3. Documented System Limitations (Phase 3B)
1. **Text-Based PDFs Only**: Only text-based PDF documents ($\le 5$ MiB, $\le 10$ pages) with usable embedded text encodings are supported. Scanned PDFs, scanned documents, Word documents (`.doc`/`.docx`), archives, and batch uploads are not supported.
2. **Text Content Only**: FraudLens evaluates textual patterns present in the reviewed text. It does not inspect visual layout, font styling, digital signatures, embedded attachments, or document authenticity.
3. **No External URL Reputation / WHOIS Checks**: URLs cited in evidence are treated strictly as textual strings. FraudLens does not perform active network probes, DNS lookups, domain registration age checks, or external reputation API queries.
4. **Scanned PDF Guidance**: Scanned PDFs contain pixel images rather than character streams; users with scanned document images should take a screenshot and use Screenshot Text Extraction.
