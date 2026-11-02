import { beforeEach, describe, expect, it, vi } from "vitest";
import { analyzeText, ApiClientError, extractScreenshot } from "../lib/api";

describe("api client: analyzeText", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("extracts backend code, reason, message, and action from 502 error response", async () => {
    const errorPayload = {
      code: "INVALID_AI_RESPONSE",
      reason: "EVIDENCE_MISMATCH",
      message: "Warning sign at index 0 contains an evidence quote not found in the submitted text.",
      action: "Ensure all cited evidence quotes are verbatim excerpts from the submitted text.",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: vi.fn().mockResolvedValue(errorPayload),
    });
    vi.stubGlobal("fetch", mockFetch);

    try {
      await analyzeText("Fictional job message", "en");
      expect.fail("Expected analyzeText to throw ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.code).toBe("INVALID_AI_RESPONSE");
      expect(apiErr.reason).toBe("EVIDENCE_MISMATCH");
      expect(apiErr.message).toBe("Warning sign at index 0 contains an evidence quote not found in the submitted text.");
      expect(apiErr.action).toBe("Ensure all cited evidence quotes are verbatim excerpts from the submitted text.");
      expect(apiErr.httpStatus).toBe(502);
    }
  });

  it("extracts AI_REQUEST_REJECTED and safe reason code from 502 error response", async () => {
    const errorPayload = {
      code: "AI_REQUEST_REJECTED",
      reason: "INVALID_SCHEMA_DEFINITION",
      message: "Gemini API rejected request with client error (HTTP 400, status: INVALID_ARGUMENT). Rejected field(s): generation_config.response_schema.additional_properties.",
      action: "Verify model generation configuration and structured output schema compatibility.",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: vi.fn().mockResolvedValue(errorPayload),
    });
    vi.stubGlobal("fetch", mockFetch);

    try {
      await analyzeText("Fictional job message", "en");
      expect.fail("Expected analyzeText to throw ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.code).toBe("AI_REQUEST_REJECTED");
      expect(apiErr.reason).toBe("INVALID_SCHEMA_DEFINITION");
      expect(apiErr.message).toContain("generation_config.response_schema.additional_properties");
      expect(apiErr.action).toBe("Verify model generation configuration and structured output schema compatibility.");
      expect(apiErr.httpStatus).toBe(502);
    }
  });

  it("handles non-JSON 502 response with sanitized fallback without crashing", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: vi.fn().mockRejectedValue(new Error("Unexpected HTML gateway page")),
    });
    vi.stubGlobal("fetch", mockFetch);

    try {
      await analyzeText("Fictional job message", "en");
      expect.fail("Expected analyzeText to throw ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.message).toBe("Analysis failed with HTTP 502.");
      expect(apiErr.httpStatus).toBe(502);
    }
  });

  it("handles user abort signal properly", async () => {
    const controller = new AbortController();
    controller.abort();

    try {
      await analyzeText("Fictional job message", "en", controller.signal);
      expect.fail("Expected analyzeText to throw for aborted signal");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.isAborted).toBe(true);
    }
  });
});

describe("api client: extractScreenshot", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends multipart request and returns parsed ScreenshotExtractionResponse on success", async () => {
    const successPayload = {
      extracted_text: "URGENT: Your account requires immediate verification.",
      ocr_language: "eng",
      character_count: 53,
      review_required: true,
      notice: "Please review and edit the extracted text.",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(successPayload),
    });
    vi.stubGlobal("fetch", mockFetch);

    const testFile = new File(["dummy_image_data"], "screenshot.png", { type: "image/png" });
    const result = await extractScreenshot(testFile, "eng");

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const call = mockFetch.mock.calls[0];
    expect(call).toBeDefined();
    const [url, options] = call as [string, RequestInit];
    expect(url).toContain("/api/v1/extract/screenshot");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);

    expect(result.extracted_text).toBe(successPayload.extracted_text);
    expect(result.ocr_language).toBe("eng");
    expect(result.character_count).toBe(53);
    expect(result.review_required).toBe(true);
  });

  it("extracts sanitized error fields on extraction failure", async () => {
    const errorPayload = {
      code: "FILE_TOO_LARGE",
      message: "Image file exceeds the maximum allowed size of 5 MiB.",
      action: "Compress, crop, or resize the screenshot before uploading.",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: vi.fn().mockResolvedValue(errorPayload),
    });
    vi.stubGlobal("fetch", mockFetch);

    const testFile = new File(["dummy_image_data"], "oversized.png", { type: "image/png" });
    try {
      await extractScreenshot(testFile, "eng");
      expect.fail("Expected extractScreenshot to throw ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.code).toBe("FILE_TOO_LARGE");
      expect(apiErr.message).toBe("Image file exceeds the maximum allowed size of 5 MiB.");
      expect(apiErr.action).toBe("Compress, crop, or resize the screenshot before uploading.");
      expect(apiErr.httpStatus).toBe(413);
    }
  });

  it("handles user abort during screenshot extraction", async () => {
    const controller = new AbortController();
    controller.abort();

    const testFile = new File(["dummy_image_data"], "screenshot.png", { type: "image/png" });
    try {
      await extractScreenshot(testFile, "eng", controller.signal);
      expect.fail("Expected extractScreenshot to throw for aborted signal");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.isAborted).toBe(true);
    }
  });
});
