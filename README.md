# FraudLens

> “Spot the warning signs. Verify your next step.”

**Author**: Arnav Kumar  
**Project Type**: Independent Portfolio Project  
**Current Phase**: Phase 4A — Local URL Structure Inspection & Multi-Modal Analysis (Offline Verified)

---

## 1. What FraudLens Aims to Do

FraudLens helps everyday users evaluate suspicious communications before sharing sensitive personal details or transferring funds. When users encounter dubious job offers demanding upfront fees, urgent payment requests, phishing messages, or unfamiliar links, FraudLens provides:
- Clear evidence-linked warning signs and psychological manipulation tactics.
- Highlighted inconsistencies and factual discrepancies.
- Verified external reputation context (e.g. domain and URL reputation).
- Explicit unknowns and areas where evidence is lacking.
- Practical, safe verification steps the user can take next.
- Bilingual explanations in English and Hindi.
- Local screenshot text extraction with human-in-the-loop review.

---

## 2. What Works in Phase 3A

### A. Local Screenshot Text Extraction (Phase 3A)
- **Local OCR Engine**:
  - `POST /api/v1/extract/screenshot` extracts text from uploaded screenshots using local Tesseract OCR and Pillow (`PIL`).
  - **Zero External Transmission of Images**: Screenshot processing runs **100% locally on the backend**. The screenshot image is **never sent to Google Gemini or any external service**.
- **Separate OCR & Explanation Languages**:
  - `ocr_language`: Controls optical character recognition (`"eng"` for English, `"hin"` for Hindi).
  - `language`: Controls downstream AI risk explanation generation (`"en"` or `"hi"`).
- **Security & Resource Limits**:
  - **Formats**: Strictly PNG and JPEG (`ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG"}`), verified by Pillow file headers to prevent extension/MIME spoofing.
  - **File Size**: Maximum 5 MiB (`5 * 1024 * 1024` bytes). Ingested in 64 KiB chunks with early abort (`FILE_TOO_LARGE` HTTP 413).
  - **Decoded Dimensions**: Maximum 12 megapixels (`12,000,000` pixels). Protected against Pillow decompression bombs (`IMAGE_TOO_LARGE` HTTP 422).
  - **Static Only**: Multi-frame GIFs, animated PNGs, and multi-frame TIFFs are rejected (`ANIMATED_IMAGE_REJECTED` HTTP 422).
  - **Subprocess Timeout**: 20-second timeout with explicit child process kill (`proc.kill()` and `await proc.wait()`) preventing orphaned worker processes.
  - **Concurrency**: Bounded by an `asyncio.Semaphore(3)` to protect CPU resources.
  - **Resource Cleanup**: In-memory processing; temporary preprocessed files are unconditionally unlinked in `finally:` blocks.
  - **Character Limits**: Extractions exceeding 10,000 characters are rejected with HTTP 422 `TEXT_TOO_LONG`, instructing the user to crop the screenshot.
  - **Cache Protection**: `Cache-Control: no-store` on all extraction responses and error responses.
- **Truthful Capabilities Reporting**:
  - `GET /api/v1/capabilities` dynamically checks whether Tesseract is installed.
  - If Tesseract is not installed on the host, it truthfully reports `screenshot_extraction: false` and `ocr_prerequisite_status: "missing_prerequisites"`. Working text analysis is **never** disabled when OCR is unavailable.
- **Human-in-the-Loop Review Area**:
  - Accessible dropzone with PNG/JPEG preview, file details, and preview URL revocation (`URL.revokeObjectURL`).
  - Extracted text is presented in an editable review textarea with prominent warning: *"OCR may misread names, amounts, URLs, or characters."*
  - Requires user to check `[ ] I have reviewed and confirmed the extracted text for accuracy` before enabling transfer to analysis.
  - **Review Invalidation**: Modifying the reviewed text automatically unchecks the confirmation box.
  - Replacing or clearing the screenshot invalidates prior extractions.
  - Clear provenance badge upon transfer: *"Analysis evaluates the submitted reviewed text only. Findings concern textual content, not image authenticity, visual tampering, sender identity, or URL reputation."*

### B. Local Text-Based PDF Document Extraction (Phase 3B)
- **Local PDF Parsing Engine**:
  - `POST /api/v1/extract/document` extracts embedded text from uploaded PDF documents using **`pypdf`** (`pypdf>=5.0.0,<6.0.0`, version 5.9.0, BSD-3-Clause license).
  - **Zero External Transmission of Documents**: Document processing runs **100% locally on the backend**. The PDF file is **never sent to Google Gemini or any external service**.
- **Worker Process Isolation**:
  - Untrusted PDF parsing runs in an independent child process (`app.services.pdf_worker`) managed by `_SyncDocumentRunner`.
  - Guarantees: Timeouts (20.0s) and cancellations forcibly kill the worker process (`proc.kill()`) and reap it via `proc.wait()`.
  - Non-blocking `cancel()` does not stall the asyncio event loop on Windows with Uvicorn `--reload`.
  - Shielded cleanup ensures the worker process is completely reaped before releasing the concurrency slot or unlinking temporary files.
  - Concurrency: Document extraction uses `_document_semaphore = asyncio.Semaphore(3)`, operating independently from OCR's `_ocr_semaphore = asyncio.Semaphore(3)`. Up to 3 OCR workers and 3 PDF workers (up to 6 extraction subprocesses total) can execute concurrently.
- **Strict Security & Resource Limits**:
  - **File Size**: Maximum 5 MiB (`5 * 1024 * 1024` bytes). Pre-spool bounded upload middleware rejects oversized uploads before disk spooling.
  - **Document Length**: Maximum 10 pages (`MAX_DOCUMENT_PAGES = 10`). Documents exceeding 10 pages are rejected with HTTP 422 `PAGE_LIMIT_EXCEEDED` (never silently truncated).
  - **Character Limits**: Maximum 10,000 characters (`MAX_EXTRACTED_CHARACTERS = 10_000`). Text exceeding this is rejected with HTTP 422 `TEXT_TOO_LONG`.
  - **Enforceable Memory Limit**: Windows Job Objects enforce a 256 MiB virtual memory ceiling per worker process on Windows before untrusted PDF parsing starts. Exceeding this triggers `MemoryError` safely mapped to `DOCUMENT_EXTRACTION_FAILED`. Best-effort RLIMIT_AS applies on POSIX if available.
  - **Bounded I/O & Output Size**: Child `stdout` and `stderr` are discarded via `subprocess.DEVNULL`. Worker output JSON is checked and restricted to $\le 1$ MiB (`MAX_WORKER_RESULT_BYTES = 1024 * 1024`) both before worker write and before parent read/decode.
  - **Security Restrictions**: Pure-Python reader does not execute PDF JavaScript, does not open embedded file attachments, does not follow external links/URIs, and does not render visual raster graphics.
  - **Encryption**: Encrypted / password-protected PDFs are rejected with safe, actionable error `ENCRYPTED_PDF_REJECTED` (HTTP 422). Passwords are not accepted in this phase.
- **Handling Pages Without Extractable Text**:
  - If entire document has no usable text: rejected with HTTP 422 `EMPTY_DOCUMENT_EXTRACTION`, explaining that scanned PDFs or image-only documents are not supported.
  - If only some pages have no text: returns structured page information, collects `empty_pages`, and includes a calibrated warning that extraction may be incomplete. Does not claim every empty page is necessarily scanned.
- **Human-in-the-Loop Review Area**:
  - Accessible dropzone with PDF validation, filename, file size, and remove file control.
  - Extracted text is presented in an editable review textarea with prominent warning: *"Extraction can alter reading order, spacing, and characters, and may omit content. Confirmation is an opportunity to correct errors, not a guarantee of accuracy."*
  - Requires user to check `[ ] I have reviewed and confirmed the extracted text for accuracy` before enabling transfer to analysis.
  - **Review Invalidation**: Modifying the reviewed text automatically unchecks the confirmation box.
  - **Nonempty Input Overwrite Protection**: Prompts for explicit confirmation before replacing existing analysis input.
  - Clear provenance badge upon transfer: *"Document Text Provenance Notice: Analysis evaluates the submitted reviewed text only. Findings concern textual content, not document authenticity, signatures, visual tampering, sender identity, or URL reputation."*

### C. Suspicious Text Analysis (Phase 2B Baseline)
- **End-to-End Suspicious Text Analysis**:
  - Full flow: paste message → select explanation language (`English` or `हिन्दी`) → Analyze Message → validated assessment with quoted evidence, uncertainties, and practical verification steps.
  - Powered by Google Gemini (`gemini-3.5-flash-lite`) using the official `google-genai` Python SDK.
  - `POST /api/v1/analyze/text` receives `{ text, language }`, validates length (1–10,000 chars), enforces strict prompt injection isolation, and returns structured findings.
- **Defensive Prompt & Pipeline Isolation**:
  - Untrusted user text is isolated inside `<UNTRUSTED_MESSAGE>` payload delimiters.
  - Instructions are delivered via trusted `types.GenerateContentConfig(system_instruction=...)` directing the model to evaluate the text passively as evidence and ignore any embedded command directives.
  - External search grounding and tools are explicitly disabled (`tools=None`).
  - Provider-side developer interaction logging is disabled where supported (`store=False`).
- **Verbatim Evidence Grounding & Cross-Field Consistency**:
  - Every cited `evidence_quote` is validated on the backend to be an exact verbatim substring of the submitted text (`quote in submitted_text`); fabricated or non-matching quotes cause immediate rejection (`INVALID_RESPONSE`).
  - Strict cross-field invariants: `warning_signs_found` requires at least 1 warning sign; `no_clear_warning_signs` and `insufficient_information` strictly require an empty warning signs array.
  - Requested language matching: The model output's `language` tag must match the requested language.
- **Plain-Text URLs & Safer Evidence Presentation**:
  - Quoted evidence strings containing URLs are strictly rendered as plain-text strings in monospace blockquotes, never as clickable HTML links (`<a>` tags).
- **Nuanced Risk Assessment & Prominent Disclaimers**:
  - `warning_signs_found`: High-visibility badge, categorized findings, and practical verification steps.
  - `no_clear_warning_signs`: Slate/neutral badge with a prominent, unmissable notice:
    > *“Important: This does not prove the message or sender is legitimate. Scammers frequently use subtle, multi-stage, or tailored communications that appear harmless in isolation.”*
  - `insufficient_information`: Cautionary badge indicating that message text lacks context to evaluate safety.
- **Application Provenance & Limitations**:
  - Every response explicitly notes `analysis_basis="submitted_text_only"`, `external_checks_performed=False`, and provides a clear limitation notice stating that AI analysis does not constitute legal or cybersecurity advice.
  - `Cache-Control: no-store` header is enforced on all analysis endpoints.
- **Client Resilience & Controls**:
  - Input preservation: User text is preserved across network retries and error conditions.
  - Loading feedback: Spinners and status indicators without misleading fake progress percentages.
  - Duplicate prevention: Analyze button is disabled while an analysis request is in flight.
  - Request aborting: Clear / Reset aborts in-flight requests via `AbortController` and resets UI state. *(Note: browser-side abort does not guarantee remote provider cancellation).*
  - Stale detection: Modifying text or switching language while viewing a previous result flags the card as stale until re-evaluated.
- **Live Analysis Status**:
  - Autonomous implementation was completed using comprehensive offline test mocks. **Live text analysis status: NOT RUN.** Manual verification instructions and a fictional-data checklist are provided below.

### D. Local URL Structure Inspection (Phase 4A)
- **Offline Structural Parsing Engine**:
  - `POST /api/v1/inspect/url` inspects URL structure without connecting to the remote server or fetching content.
  - **Zero Outbound Network Guarantee**: The inspection pipeline makes **strictly zero network connections**. No DNS resolution (`socket.getaddrinfo`), no socket connections, no HTTP requests, no WHOIS queries, and no AI calls.
- **Separation of Available vs. Planned Capabilities**:
  - **Available**: Local URL structure inspection (decomposing scheme, destination host, port, userinfo, IP addresses, punycode, and PSL registrable domain).
  - **Planned**: External reputation checks (Google Safe Browsing, VirusTotal, WHOIS domain age).
  - *Core Principle*: Structural inspection alone **never** proves a URL is safe or malicious. Clean structure does not guarantee legitimacy; non-default ports or IP addresses are not inherently fraudulent. Neither establishes sender identity.
- **Parsing Libraries & PSL Derivation**:
  - Python standard library `urllib.parse.urlsplit` (never a single regular expression).
  - Python `ipaddress` for IPv4/IPv6 classification, bracketed IPv6 support (`[::1]`), and scope categorization (`private`, `loopback`, `link_local`, `reserved`, `public`).
  - `idna` (version 3.20) for IDNA 2008 Unicode and ASCII punycode validation and conversion.
  - `tldextract` (version 5.4.0) with bundled offline Public Suffix List snapshot:
    - Runtime downloads strictly disabled (`suffix_list_urls=()`, `cache_dir=None`).
    - Configured with RFC 2606 / RFC 6761 reserved testing TLDs (`invalid`, `test`, `example`, `localhost`).
    - Derives registrable domains reliably without arbitrary two-label approximations (e.g. handles `example.co.uk`, `service.gov.in`, `com.au`).
- **Deterministic Structural Observations**:
  - `unencrypted_http`: Informational. Unencrypted transit; notes that HTTP alone does not prove fraud.
  - `userinfo_present`: Caution. Credentials before `@` in netloc do not represent the destination domain; highlights actual destination host.
  - `ip_literal_host`: Caution. Destination is a direct IP address. Scope noted (private, loopback, public). Notes an IP address is not inherently malicious.
  - `special_use_address`: Informational. Explains special-use/private/loopback scope without asserting network reachability.
  - `punycode_hostname`: Informational. Displays both Unicode and ASCII punycode (`xn--...`). Explains IDN legitimacy alongside lookalike caveat.
  - `non_default_port`: Informational. Identifies port without labeling it malicious.
  - `deep_subdomain_hierarchy`: Caution. Threshold >= 3 subdomain levels. Explains deep subdomain risk objectively.
- **Security & Privacy Boundaries**:
  - Maximum URL length: 2,048 characters (`MAX_URL_LENGTH = 2048`).
  - Pre-parse control character check: rejects strings with ASCII control characters (< 32 or 127) or embedded spaces.
  - Explicit scheme requirement: strictly requires `http://` or `https://`. Schemes are never silently guessed or repaired.
  - `Cache-Control: no-store` on all success (200) and validation failure (422) responses.
  - Zero URL logging or persistence: submitted URLs are never logged or saved on the server.
- **Frontend Presentation**:
  - Accessible `UrlInspector` component in `frontend/src/features/url/UrlInspector.tsx`.
  - Destination hostname is prominently styled in a highlighted card so users immediately see where the link actually points.
  - Submitted URL is displayed strictly as **plain text** with word break (`break-all`), **NEVER as an `<a>` tag or clickable HTML link**.
  - Edit invalidation marks previous findings as stale; `AbortController` discards pending requests on edit, reset, or re-inspection.

---

## 3. Selected AI Model & Documentation Sources

- **Provider**: Google Gemini API (`AI_PROVIDER=gemini`)
- **SDK**: Official `google-genai` Python SDK (`google-genai>=2.0.0,<3.0.0`, installed `2.33.0`)
- **Selected Model ID**: `gemini-3.5-flash-lite`
  - *Models Documentation*: https://ai.google.dev/gemini-api/docs/models
  - *Structured Outputs Documentation*: https://ai.google.dev/gemini-api/docs/structured-output
  - *Dynamic Rate Limits Console*: https://aistudio.google.com/rate-limit
  - *Terms of Service*: https://ai.google.dev/gemini-api/terms
- **Historical Candidate & Investigation (`gemini-3.8-flash`)**:
  - Phase 2A was initially prepared against `gemini-3.8-flash`.
  - Live smoke testing with `gemini-3.8-flash` returned HTTP 504 `DEADLINE_EXCEEDED` (~30s) and HTTP 503 `UNAVAILABLE` (6.29s) under `generate_content`, and client timeouts (~61s) under `interactions.create`.
  - Standalone transport diagnostics confirmed that exactly 1 transport attempt was made with zero unintended retries.
  - While AI Studio playground returned Hello, API gateway calls to `gemini-3.8-flash` consistently failed. The root cause remains **unknown / unconfirmed** (potential gateway queue delays, model provisioning latency, or capacity constraints on the free-tier developer endpoint).
  - Transitioning to **`gemini-3.5-flash-lite`** resolved the issue immediately with successful live responses.
- **Model Configurability**: Configurable via `AI_MODEL` in `backend/.env`. The application will never silently switch models.

---

## 4. Free Tier & Data Privacy Boundary

- **Dynamic Quotas**: Free tier quotas and rate limits are managed dynamically per project by Google AI Studio. Check your active limits directly in the [Google AI Studio Rate Limit page](https://aistudio.google.com/rate-limit).
- **Fictional Data Only**: On the Google AI Studio Free Tier, prompts and outputs may be processed by Google for service improvements and reviewed by human annotators. **Never submit real, sensitive personal evidence on the free tier.**
- **Storage Setting (`store=False`)**: The adapter sets `store=False` in `GenerateContentConfig` to opt out of developer-owned interaction logging in Google AI Studio project history where supported.
- **No Zero Retention Guarantee**: Setting `store=False` does **not** provide zero data retention (ZDR) and does not override Google's safety/abuse monitoring or free-tier service terms. Strict Zero Data Retention is an enterprise compliance feature available on Google Cloud Vertex AI, not the standard Gemini Developer API.

---

## 5. Local Setup & Secret Entry Instructions (Windows PowerShell)

> **Important**: Never paste your API key into chat or shell command lines. Keep it strictly in your local `backend/.env` file.

### Step 1: Environment Configuration

Create `backend\.env` from `backend\.env.example` only if it does not already exist:

```powershell
if (-not (Test-Path backend\.env)) {
    Copy-Item backend\.env.example backend\.env
}
```

### Step 2: Open and Edit in Notepad

Open the backend `.env` file in Notepad:

```powershell
notepad.exe backend\.env
```

Inside Notepad, set these values:
- `AI_PROVIDER=gemini`
- `AI_MODEL=gemini-3.5-flash-lite`
- `AI_API_KEY=YOUR_ACTUAL_GEMINI_KEY_HERE`

Preserve the existing `ALLOWED_ORIGINS` setting:
```env
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AI_PROVIDER=gemini
AI_MODEL=gemini-3.5-flash-lite
AI_API_KEY=YOUR_ACTUAL_GEMINI_KEY_HERE
```

Save the file (`Ctrl + S`) and close Notepad.

*(Git is verified to ignore `backend/.env`; it will not be committed or tracked).*

---

### Step 3: (Optional) Install Tesseract-OCR for Screenshot Text Extraction (Phase 3A)

Screenshot text extraction executes locally on the backend using Tesseract OCR.
If Tesseract is not installed, FraudLens continues to work normally for direct text pasting, and truthfully reports `screenshot_extraction: false` in `GET /api/v1/capabilities`.

To enable screenshot text extraction on Windows:
1. Download the official installer from UB-Mannheim:
   https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer (e.g. `tesseract-ocr-w64-setup-5.5.0.exe`).
3. Under **Components to install**, expand **Additional language data (download)** and check **Hindi**.
4. Complete installation to the default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
5. *(Optional)* If installed to a non-standard directory, add this line in `backend/.env`:
   ```env
   TESSERACT_CMD=D:\CustomPath\Tesseract-OCR\tesseract.exe
   ```
6. Verify in PowerShell:
   ```powershell
   & "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
   & "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
   ```

---

### Step 4: Run the Synthetic Smoke Test (CLI)

Before starting the web server, run the synthetic smoke test from the `backend` directory to verify your key and model connectivity:

```powershell
Set-Location D:\FraudLens\backend
.\.venv\Scripts\python.exe -m scripts.check_gemini
```

Verified live output:
```text
==================================================
FraudLens — Synthetic Gemini Connectivity Verification
==================================================
Provider: gemini
Model ID: gemini-3.5-flash-lite
--------------------------------------------------
Result: SUCCESS
Elapsed Time: 1.80s
Schema Validation: PASSED (Devanagari Script: Yes)
Harmless Synthetic Output:
  English: Hello! How can I help you today?
  Hindi:   नमस्ते! मैं आज आपकी क्या मदद कर सकता हूँ?
--------------------------------------------------
Note: Hindi script detection confirms format presence, not translation quality.
Connectivity check complete. No user evidence was submitted or retained.
```

- **Live Plain-Text Diagnostic**: Also verified via `.\.venv\Scripts\python.exe -m scripts.diagnose_raw_gemini` (`SUCCESS`, 3.65s elapsed).
- **Separation of Concerns**: CLI verification (`check_gemini.py`) validates the Gemini API key, adapter configuration, and structured output parsing out-of-band. The running backend endpoint `GET /api/v1/capabilities` intentionally continues to report `ai_connection="not_tested"` at server runtime; it does not claim a live connection until live text analysis is executed.
- **Text Analysis Status**: Text analysis is active in Phase 2B (`POST /api/v1/analyze/text`), supported by strict evidence grounding, defensive prompt isolation, and 8 safe diagnostic reason codes.

---

### Step 4: Backend Startup

In a **dedicated PowerShell terminal**:

```powershell
Set-Location D:\FraudLens\backend
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

### Step 5: Frontend Startup

In a **second PowerShell terminal**:

```powershell
Set-Location D:\FraudLens\frontend
node .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173` in your browser.

---

## 6. Running Verification Commands

### Backend Verification (pytest)
In a PowerShell terminal from the project root:
```powershell
.\backend\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests -v
```

**Result**: 167 passed tests covering:
- Health response contract (`GET /api/v1/health`).
- Capabilities reporting (`GET /api/v1/capabilities`) for text analysis, OCR, and document extraction.
- Secret masking (`ai_api_key` never exposed).
- Strict validation (blank text, character limit, language restrictions, extra field rejection).
- Validation error sanitization (markers never echoed).
- Text analysis routing, exact evidence substring validation, and cross-field invariants.
- 8 safe output diagnostic reason codes and provider request rejection handling.
- Gemini adapter missing key / placeholder rejection.
- Real SDK configuration object verification (`HttpOptions`, `GenerateContentConfig`, `store=False`, `attempts=1`, `aclose()`).
- OCR image validation (PNG, JPEG, extension/MIME spoofing, max 5 MiB file size, max 12 MP decoded limits, multi-frame/animated rejection, decompression-bomb defense).
- OCR dual event loop compatibility (Windows `_WindowsSelectorEventLoop` under Uvicorn `--reload` and `ProactorEventLoop`), worker thread fallback, process kill and reaping on timeout, and temporary file unlinking.
- Real local OCR endpoint execution (`POST /api/v1/extract/screenshot`) and outbound network isolation (zero Gemini calls during OCR).
- PDF document extraction (`POST /api/v1/extract/document`) with `pypdf`, worker process isolation, timeout termination, child process reaping, event loop responsiveness, and repeated cancellation shielding.
- Single-page, multipage, and Hindi Unicode text extraction, empty doc rejection, incomplete page warnings, 10-page limit, and 10,000-character limit.
- Pre-spool bounded multipart upload rejection (5 MiB + 64 KiB overhead), streaming oversize abort, and Starlette `SpooledTemporaryFile` cleanup.
- Outbound network isolation (zero Gemini calls during document extraction).

### Frontend Verification (Vitest, Lint, TypeScript, Build)
In a PowerShell terminal inside `frontend`:
```powershell
Set-Location frontend

# 1. Run unit tests with Vitest & React Testing Library
npm test

# 2. Run TypeScript strict type-checking
npx tsc -b

# 3. Run ESLint code quality checks
npm run lint

# 4. Run production bundle build
npm run build
```

**Results (Phase 3B Final)**:
- **Backend Tests (pytest)**: 167 tests passed in 20.65s.
- **Frontend Tests (Vitest)**: 49 tests passed in 19.70s.
- **TypeScript (tsc -b)**: 0 errors.
- **ESLint**: 0 errors, 0 warnings.
- **Vite build**: production bundle created successfully in `dist/` (195.56 kB JS, 23.55 kB CSS).

---

## 7. Application Startup Instructions (Windows PowerShell)

To start both services locally:

### Terminal 1: Start Backend (FastAPI)
```powershell
Set-Location D:\FraudLens\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Terminal 2: Start Frontend (Vite)
```powershell
Set-Location D:\FraudLens\frontend
node .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 --strictPort
```

Once running, navigate to `http://127.0.0.1:5173` in your browser.

---

## 8. Manual Testing Checklist (Fictional Data Only)

> **Important**: Never submit real, sensitive personal data or active banking information. Use only synthetic or fictional test examples.

### Example 1: Advance-Fee Remote Job Offer
- **Input Text**:
  > “Congratulations! You have been selected for a remote Data Entry position paying $45/hour. To secure your onboarding kit and software license, please transfer a refundable registration deposit of $150 to registration@example.invalid immediately.”
- **Language**: English
- **Expected Assessment**: `warning_signs_found`
- **Qualitative Expectations**:
  - Badge: "Warning Signs Detected"
  - Category: Job / Employment Offer
  - Warning Signs: Highlighting the advance fee deposit ($150) and unrealistic pay/selection urgency.
  - Quoted Evidence: Exact quote from text formatted as plain text (no clickable links).
  - Practical Verification Steps: Directing the user to check the employer's official careers portal and never pay for a job offer.

### Example 2: OTP / Account Suspension Phishing
- **Input Text**:
  > “URGENT: Your Apex Bank card is suspended due to unusual activity. Avoid permanent closure by verifying your PIN and OTP immediately at https://apexbank-security-verify.example.invalid/login.”
- **Language**: English or हिन्दी
- **Expected Assessment**: `warning_signs_found`
- **Qualitative Expectations**:
  - Badge: "Warning Signs Detected"
  - Category: Phishing / Impersonation
  - Warning Signs: Highlighting urgency and the request for sensitive credentials/OTP.
  - Plain-Text URL: The URL `https://apexbank-security-verify.example.invalid/login` must appear as a monospace plain text quote, NOT a clickable link.
  - Practical Verification Steps: Advise calling the phone number on the back of the physical bank card.

### Example 3: Routine Meeting Reminder (No Red Flags)
- **Input Text**:
  > “Hi team, just a reminder that our weekly project sync is scheduled for tomorrow at 10:00 AM in Conference Room B. Please review the shared slides before the meeting.”
- **Language**: English
- **Expected Assessment**: `no_clear_warning_signs`
- **Qualitative Expectations**:
  - Badge: "No Clear Warning Signs Found"
  - Prominent Cautionary Notice:
    > *“Important: This does not prove the message or sender is legitimate. Scammers frequently use subtle, multi-stage, or tailored communications that appear harmless in isolation.”*
  - Zero warning signs displayed.
  - Guidance suggesting standard verification via known channels if unsolicited.

---

## 9. Manual Screenshot Test Checklist (Phase 3A)

When Tesseract OCR is installed on the host, use this checklist to verify the screenshot workflow:

1. **PNG Selection & Preview**:
   - Select a valid PNG screenshot ($\le 5$ MiB).
   - Verify local preview thumbnail renders with filename and file size.
   - Verify preview URL is cleaned up if "Remove" is clicked.
2. **Local Extraction (Zero Google Calls)**:
   - Select OCR language (`EN (eng)` or `HI (hin)`).
   - Click "Extract Text".
   - Confirm extraction finishes locally without network activity to Google.
3. **Editable Review Area**:
   - Verify extracted text appears in the editable textarea with character counter.
   - Verify notice: *"OCR may misread names, amounts, URLs, or characters."*
   - Verify "Use Reviewed Text for Analysis" is disabled until `[x] I have reviewed and confirmed the extracted text for accuracy` is checked.
4. **Review Invalidation**:
   - Check the confirmation box.
   - Edit any character in the textarea.
   - Verify the confirmation box automatically unchecks and transfer is disabled.
5. **Transfer to Analysis**:
   - Re-check the confirmation box and click "Use Reviewed Text for Analysis".
   - Verify text is transferred to the main analysis textarea.
   - Verify the "Screenshot Text Provenance Notice" badge appears.
   - Click "Analyze Message" to run Gemini analysis on the exact reviewed text.
6. **Error Handlers**:
   - Try uploading a `.txt` file or corrupt image: verify `INVALID_IMAGE` error.
   - Try uploading an image $> 5$ MiB: verify `FILE_TOO_LARGE` error.

---

## 10. Manual URL Inspection Test Checklist (Phase 4A)

Use this checklist with fictional test URLs to verify the URL structure inspection workflow in the browser:

1. **Ordinary HTTPS URL**:
   - Input: `https://example.com/login`
   - Verify prominent destination host card shows `example.com`.
   - Verify submitted URL is rendered as plain text (not a clickable link).
   - Verify observations state no anomalies detected.
2. **Userinfo URL with Brand Impersonation Pattern**:
   - Input: `https://mybank.com@destination.invalid/account`
   - Verify destination host card prominently displays `destination.invalid` (NOT `mybank.com`).
   - Verify caution observation highlights that `mybank.com` is authentication userinfo, not the destination server.
3. **Misleading Deep Subdomain**:
   - Input: `https://mybank.com.security.destination.invalid/portal`
   - Verify destination host displays `mybank.com.security.destination.invalid`.
   - Verify Registrable Domain displays `destination.invalid`.
   - Verify Caution observation: Deep Subdomain Hierarchy (3 levels: `mybank`, `com`, `security`).
4. **Valid Unicode IDN / Punycode**:
   - Input: `https://münchen.de/portal`
   - Verify destination host displays `münchen.de`.
   - Verify ASCII Punycode displays `xn--mnchen-3ya.de`.
   - Verify Informational observation explains Internationalized Domain Names.
5. **Direct IP Address & Non-Default Port**:
   - Input: `http://192.168.1.1:8080/admin`
   - Verify destination host displays `192.168.1.1` (IPv4, private scope).
   - Verify Informational observations for unencrypted HTTP, non-default port 8080, and private address scope.
6. **Input Validation & Stale Detection**:
   - Enter `ftp://files.example.com` -> verify `UNSUPPORTED_SCHEME` error callout with actionable guidance.
   - Enter `https://example.com:99999` -> verify `INVALID_PORT` error callout.
   - Modify the input text after inspection -> verify stale banner: *"Input modified: The URL was changed since the last inspection."*
   - Click Reset -> verify input and results are cleared.

---

## 11. Troubleshooting

### 1. Missing or Placeholder Key Error
If the backend returns HTTP 503 `AI_CONFIGURATION_MISSING`:
- Open `backend\.env` in Notepad and verify `AI_PROVIDER=gemini` and `AI_API_KEY` contains your real key starting with `AIza...`.

### 2. Authentication Failed (401/403)
If the backend returns HTTP 503 `AI_AUTH_FAILED`:
- Check that the key copied from Google AI Studio is active and has no trailing spaces or expired project permissions.

### 3. Model Unavailable (404)
If the backend returns HTTP 503 `AI_MODEL_UNAVAILABLE`:
- Verify that `AI_MODEL=gemini-3.5-flash-lite` in `backend/.env`.

### 4. Quota Exceeded (429)
If the backend returns HTTP 429 `AI_QUOTA_EXCEEDED`:
- The project has reached its free-tier rate limits. Check the [Google AI Studio Rate Limit page](https://aistudio.google.com/rate-limit).

### 5. Local OCR Unavailable (HTTP 503 `OCR_UNAVAILABLE`)
If screenshot extraction reports that Tesseract is not installed:
- Install Tesseract-OCR (v5.x) on Windows and ensure `tesseract.exe` is in PATH or specify `TESSERACT_CMD` in `backend/.env`.
- Text analysis remains fully operational by pasting text directly into the form.

### 6. OCR Language Not Installed (HTTP 503 `OCR_LANGUAGE_NOT_INSTALLED`)
If Hindi OCR extraction fails:
- Ensure `hin.traineddata` was selected during installation or placed into Tesseract's `tessdata` folder (`C:\Program Files\Tesseract-OCR\tessdata`).

### 7. File Too Large (HTTP 413 `FILE_TOO_LARGE`)
If screenshot extraction fails with size limits:
- Screenshots must be $\le 5$ MiB. Crop the image to focus on the suspicious message area before uploading.

### 8. Occupied Port (8000 or 5173)
If port 8000 or 5173 is already in use by another service:
- Check what process is using the port:
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
  ```
- If you need to run the backend on port 8001:
  ```powershell
  ..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
  ```
- Update `frontend/.env`:
  ```env
  VITE_API_BASE_URL=http://127.0.0.1:8001
  ```
