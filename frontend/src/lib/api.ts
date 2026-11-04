import {
  BackendCheckResult,
  CapabilitiesResponse,
  DocumentExtractionResponse,
  HealthResponse,
  Language,
  OcrLanguage,
  ScreenshotExtractionResponse,
  TextAnalysisResponse,
  UrlInspectionResponse,
} from "../types/api";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const SHORT_REQUEST_TIMEOUT_MS = 5000;
const ANALYSIS_REQUEST_TIMEOUT_MS = 38000; // Allow 30s provider timeout + network overhead to report backend diagnostics cleanly
const EXTRACTION_REQUEST_TIMEOUT_MS = 25000; // 20s backend timeout + network overhead

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly isNetworkError = false,
    public readonly isAborted = false,
    public readonly code?: string,
    public readonly action?: string,
    public readonly httpStatus?: number,
    public readonly reason?: string
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

async function fetchWithTimeout(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs: number = SHORT_REQUEST_TIMEOUT_MS,
  externalSignal?: AbortSignal
): Promise<Response> {
  const internalController = new AbortController();
  const timeoutId = setTimeout(() => internalController.abort(), timeoutMs);

  // If an external signal is provided, forward abort to the request controller
  const handleExternalAbort = () => {
    internalController.abort();
  };

  if (externalSignal) {
    if (externalSignal.aborted) {
      clearTimeout(timeoutId);
      throw new ApiClientError("Request was canceled.", false, true);
    }
    externalSignal.addEventListener("abort", handleExternalAbort, { once: true });
  }

  try {
    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
      ...options,
      signal: internalController.signal,
      headers: {
        Accept: "application/json",
        ...options.headers,
      },
    });
    return response;
  } catch (err: unknown) {
    if (externalSignal?.aborted) {
      throw new ApiClientError("Analysis request was canceled.", false, true);
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiClientError(
        "Backend request timed out. Please check if the server is responsive.",
        true
      );
    }
    throw new ApiClientError(
      "Unable to reach the FraudLens backend service. Ensure the backend is running.",
      true
    );
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", handleExternalAbort);
    }
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetchWithTimeout("/api/v1/health");
  if (!res.ok) {
    throw new ApiClientError(`Backend health check failed (status ${res.status}).`);
  }
  try {
    const data = await res.json();
    if (data && typeof data.status === "string" && typeof data.service === "string") {
      return data as HealthResponse;
    }
    throw new Error("Invalid health response schema");
  } catch {
    throw new ApiClientError("Received an invalid response format from backend health check.");
  }
}

export async function fetchCapabilities(): Promise<CapabilitiesResponse> {
  const res = await fetchWithTimeout("/api/v1/capabilities");
  if (!res.ok) {
    throw new ApiClientError(`Backend capabilities check failed (status ${res.status}).`);
  }
  try {
    const data = await res.json();
    if (data && typeof data.text_analysis === "boolean") {
      return data as CapabilitiesResponse;
    }
    throw new Error("Invalid capabilities response schema");
  } catch {
    throw new ApiClientError("Received an invalid response format from backend capabilities check.");
  }
}

export async function checkBackendConnection(): Promise<BackendCheckResult> {
  const [health, capabilities] = await Promise.all([
    fetchHealth(),
    fetchCapabilities(),
  ]);
  return { health, capabilities };
}

export async function analyzeText(
  text: string,
  language: Language,
  signal?: AbortSignal
): Promise<TextAnalysisResponse> {
  const res = await fetchWithTimeout(
    "/api/v1/analyze/text",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        language,
      }),
    },
    ANALYSIS_REQUEST_TIMEOUT_MS,
    signal
  );

  const responseData: Record<string, any> | null = await res.json().catch(() => null);

  if (!res.ok) {
    const errorPayload =
      responseData && typeof responseData === "object"
        ? (responseData.error && typeof responseData.error === "object"
            ? responseData.error
            : responseData.detail && typeof responseData.detail === "object"
            ? responseData.detail
            : responseData)
        : null;

    let message = `Analysis failed with HTTP ${res.status}.`;
    let code: string | undefined;
    let reason: string | undefined;
    let action: string | undefined;

    if (errorPayload && typeof errorPayload === "object") {
      if (typeof errorPayload.message === "string" && errorPayload.message.trim()) {
        message = errorPayload.message.trim();
      }
      if (typeof errorPayload.code === "string" && errorPayload.code.trim()) {
        code = errorPayload.code.trim();
      }
      if (typeof errorPayload.reason === "string" && errorPayload.reason.trim()) {
        reason = errorPayload.reason.trim();
      }
      if (typeof errorPayload.action === "string" && errorPayload.action.trim()) {
        action = errorPayload.action.trim();
      }
    } else if (typeof responseData?.detail === "string") {
      message = responseData.detail;
    }

    throw new ApiClientError(
      message,
      false,
      false,
      code,
      action,
      res.status,
      reason
    );
  }

  if (!responseData || typeof responseData !== "object" || !responseData.assessment) {
    throw new ApiClientError("Backend returned an invalid analysis response format.");
  }

  return responseData as TextAnalysisResponse;
}

export async function extractScreenshot(
  file: File,
  ocrLanguage: OcrLanguage,
  signal?: AbortSignal
): Promise<ScreenshotExtractionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("ocr_language", ocrLanguage);

  const res = await fetchWithTimeout(
    "/api/v1/extract/screenshot",
    {
      method: "POST",
      body: formData,
    },
    EXTRACTION_REQUEST_TIMEOUT_MS,
    signal
  );

  const responseData: Record<string, any> | null = await res.json().catch(() => null);

  if (!res.ok) {
    let message = `Extraction failed with HTTP ${res.status}.`;
    let code: string | undefined;
    let reason: string | undefined;
    let action: string | undefined;

    if (responseData && typeof responseData === "object") {
      if (typeof responseData.message === "string" && responseData.message.trim()) {
        message = responseData.message.trim();
      }
      if (typeof responseData.code === "string" && responseData.code.trim()) {
        code = responseData.code.trim();
      }
      if (typeof responseData.reason === "string" && responseData.reason.trim()) {
        reason = responseData.reason.trim();
      }
      if (typeof responseData.action === "string" && responseData.action.trim()) {
        action = responseData.action.trim();
      }
    }

    throw new ApiClientError(
      message,
      false,
      false,
      code,
      action,
      res.status,
      reason
    );
  }

  if (
    !responseData ||
    typeof responseData !== "object" ||
    typeof responseData.extracted_text !== "string"
  ) {
    throw new ApiClientError("Backend returned an invalid extraction response format.");
  }

  return responseData as ScreenshotExtractionResponse;
}

export async function extractDocument(
  file: File,
  signal?: AbortSignal
): Promise<DocumentExtractionResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetchWithTimeout(
    "/api/v1/extract/document",
    {
      method: "POST",
      body: formData,
    },
    EXTRACTION_REQUEST_TIMEOUT_MS,
    signal
  );

  const responseData: Record<string, any> | null = await res.json().catch(() => null);

  if (!res.ok) {
    let message = `Document extraction failed with HTTP ${res.status}.`;
    let code: string | undefined;
    let reason: string | undefined;
    let action: string | undefined;

    if (responseData && typeof responseData === "object") {
      if (typeof responseData.message === "string" && responseData.message.trim()) {
        message = responseData.message.trim();
      }
      if (typeof responseData.code === "string" && responseData.code.trim()) {
        code = responseData.code.trim();
      }
      if (typeof responseData.reason === "string" && responseData.reason.trim()) {
        reason = responseData.reason.trim();
      }
      if (typeof responseData.action === "string" && responseData.action.trim()) {
        action = responseData.action.trim();
      }
    }

    throw new ApiClientError(
      message,
      false,
      false,
      code,
      action,
      res.status,
      reason
    );
  }

  if (
    !responseData ||
    typeof responseData !== "object" ||
    typeof responseData.combined_text !== "string"
  ) {
    throw new ApiClientError("Backend returned an invalid document extraction response format.");
  }

  return responseData as DocumentExtractionResponse;
}

export async function inspectUrl(
  url: string,
  signal?: AbortSignal
): Promise<UrlInspectionResponse> {
  const res = await fetchWithTimeout(
    "/api/v1/inspect/url",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url }),
    },
    SHORT_REQUEST_TIMEOUT_MS,
    signal
  );

  const responseData: Record<string, any> | null = await res.json().catch(() => null);

  if (!res.ok) {
    let message = `URL inspection failed with HTTP ${res.status}.`;
    let code: string | undefined;
    let reason: string | undefined;
    let action: string | undefined;

    if (responseData && typeof responseData === "object") {
      if (typeof responseData.message === "string" && responseData.message.trim()) {
        message = responseData.message.trim();
      }
      if (typeof responseData.code === "string" && responseData.code.trim()) {
        code = responseData.code.trim();
      }
      if (typeof responseData.reason === "string" && responseData.reason.trim()) {
        reason = responseData.reason.trim();
      }
      if (typeof responseData.action === "string" && responseData.action.trim()) {
        action = responseData.action.trim();
      }
    }

    throw new ApiClientError(
      message,
      false,
      false,
      code,
      action,
      res.status,
      reason
    );
  }

  if (
    !responseData ||
    typeof responseData !== "object" ||
    typeof responseData.hostname !== "string"
  ) {
    throw new ApiClientError("Backend returned an invalid URL inspection response format.");
  }

  return responseData as UrlInspectionResponse;
}
