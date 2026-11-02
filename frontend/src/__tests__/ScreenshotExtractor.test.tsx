import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScreenshotExtractor } from "../features/screenshot/ScreenshotExtractor";
import * as api from "../lib/api";
import { BackendConnectionState } from "../types/api";

describe("ScreenshotExtractor Component", () => {
  const connectedWithOcr: BackendConnectionState = {
    status: "connected",
    capabilities: {
      text_analysis: true,
      screenshot_extraction: true,
      url_reputation: false,
      saved_cases: false,
      ai_connection: "not_tested",
      ai_configuration: "present",
      ocr_languages: ["eng", "hin"],
      ocr_prerequisite_status: "ready",
    },
  };

  const connectedWithoutOcr: BackendConnectionState = {
    status: "connected",
    capabilities: {
      text_analysis: true,
      screenshot_extraction: false,
      url_reputation: false,
      saved_cases: false,
      ai_connection: "not_tested",
      ai_configuration: "present",
      ocr_languages: [],
      ocr_prerequisite_status: "missing_prerequisites",
    },
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:http://localhost:5173/mock-preview-id"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("renders dropzone and displays honest warning when OCR is unavailable on server", () => {
    render(
      <ScreenshotExtractor
        backendState={connectedWithoutOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    expect(
      screen.getByRole("heading", { name: /Screenshot Text Extraction/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Local OCR Engine Unavailable on Server Host/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Tesseract-OCR is not installed/i)
    ).toBeInTheDocument();

    const fileInput = screen.getByLabelText(/Choose Screenshot Image/i);
    expect(fileInput).toBeInTheDocument();
  });

  it("rejects unsupported file extensions with clear error message", async () => {
    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    const txtFile = new File(["some text"], "sample.txt", { type: "text/plain" });

    fireEvent.change(fileInput, { target: { files: [txtFile] } });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/Unsupported file format/i)).toBeInTheDocument();
      expect(screen.getByText(/INVALID_IMAGE/i)).toBeInTheDocument();
    });
  });

  it("rejects files exceeding 5 MiB with FILE_TOO_LARGE error", async () => {
    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    // 6 MiB file
    const largeBlob = new Uint8Array(6 * 1024 * 1024);
    const largeFile = new File([largeBlob], "giant.png", { type: "image/png" });

    fireEvent.change(fileInput, { target: { files: [largeFile] } });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/exceeds the 5 MiB maximum limit/i)).toBeInTheDocument();
      expect(screen.getByText(/FILE_TOO_LARGE/i)).toBeInTheDocument();
    });
  });

  it("creates preview and enables Extract Text for valid PNG", async () => {
    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    const validFile = new File(["fake_png_data"], "scam_offer.png", { type: "image/png" });

    fireEvent.change(fileInput, { target: { files: [validFile] } });

    await waitFor(() => {
      expect(screen.getByText("scam_offer.png")).toBeInTheDocument();
      expect(URL.createObjectURL).toHaveBeenCalledWith(validFile);
      const previewImg = screen.getByAltText(/Selected screenshot preview/i);
      expect(previewImg).toHaveAttribute("src", "blob:http://localhost:5173/mock-preview-id");
    });

    const extractBtn = screen.getByRole("button", { name: /Extract Text/i });
    expect(extractBtn).toBeEnabled();
  });

  it("completes extraction and requires explicit review confirmation before analysis transfer", async () => {
    const user = userEvent.setup();
    const mockOnUse = vi.fn();

    vi.spyOn(api, "extractScreenshot").mockResolvedValue({
      extracted_text: "Congratulations! You won a $1000 prize. Claim now.",
      ocr_language: "eng",
      character_count: 52,
      review_required: true,
      notice: "Please review and edit the extracted text.",
    });

    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={mockOnUse}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    const validFile = new File(["fake_png_data"], "scam.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [validFile] } });

    const extractBtn = screen.getByRole("button", { name: /Extract Text/i });
    await user.click(extractBtn);

    await waitFor(() => {
      expect(screen.getByText(/Review Extracted Text/i)).toBeInTheDocument();
      expect(screen.getByText(/OCR may misread names, amounts, URLs, or characters/i)).toBeInTheDocument();
      expect(screen.getByDisplayValue(/Congratulations! You won a \$1000 prize/i)).toBeInTheDocument();
    });

    const transferBtn = screen.getByRole("button", { name: /Use Reviewed Text for Analysis/i });
    expect(transferBtn).toBeDisabled();

    // Check review confirmation checkbox
    const reviewCheckbox = screen.getByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    expect(reviewCheckbox).not.toBeChecked();

    await user.click(reviewCheckbox);
    expect(reviewCheckbox).toBeChecked();
    expect(transferBtn).toBeEnabled();

    // Click transfer to analysis
    await user.click(transferBtn);
    expect(mockOnUse).toHaveBeenCalledWith("Congratulations! You won a $1000 prize. Claim now.");
  });

  it("invalidates review confirmation whenever extracted text is edited", async () => {
    const user = userEvent.setup();

    vi.spyOn(api, "extractScreenshot").mockResolvedValue({
      extracted_text: "Initial extracted message.",
      ocr_language: "eng",
      character_count: 26,
      review_required: true,
      notice: "Please review.",
    });

    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "test.png", { type: "image/png" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    const reviewCheckbox = await screen.findByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    await user.click(reviewCheckbox);
    expect(reviewCheckbox).toBeChecked();

    const textarea = screen.getByLabelText(/Review Extracted Text/i);
    await user.type(textarea, " with user edits.");

    // Confirmation must automatically be unchecked
    expect(reviewCheckbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: /Use Reviewed Text for Analysis/i })).toBeDisabled();
  });

  it("changing OCR language invalidates prior extraction and review confirmation", async () => {
    const user = userEvent.setup();

    vi.spyOn(api, "extractScreenshot").mockResolvedValue({
      extracted_text: "Original English extraction.",
      ocr_language: "eng",
      character_count: 28,
      review_required: true,
      notice: "Please review.",
    });

    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "test.png", { type: "image/png" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    const reviewCheckbox = await screen.findByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    await user.click(reviewCheckbox);
    expect(reviewCheckbox).toBeChecked();
    expect(screen.getByDisplayValue("Original English extraction.")).toBeInTheDocument();

    // Toggle OCR language to Hindi
    const hiButton = screen.getByRole("button", { name: /HI \(hin\)/i });
    await user.click(hiButton);

    // Prior extraction must be invalidated and review box cleared
    expect(screen.queryByDisplayValue("Original English extraction.")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    })).not.toBeInTheDocument();
  });

  it("changing OCR language while extraction is in flight discards late response", async () => {
    const user = userEvent.setup();
    let resolvePromise: (value: any) => void = () => {};
    const deferred = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    vi.spyOn(api, "extractScreenshot").mockReturnValue(deferred as any);

    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "test.png", { type: "image/png" })] },
    });

    const extractBtn = screen.getByRole("button", { name: /Extract Text/i });
    await user.click(extractBtn);

    // Extraction is now in flight
    expect(screen.getByText(/Extracting Text/i)).toBeInTheDocument();

    // Change OCR language while in flight
    const hiButton = screen.getByRole("button", { name: /HI \(hin\)/i });
    await user.click(hiButton);

    // Resolve the old in-flight promise
    resolvePromise({
      extracted_text: "Late resolved old extraction.",
      ocr_language: "eng",
      character_count: 29,
      review_required: true,
      notice: "Please review.",
    });

    // Verify late response cannot restore review text or enable transfer
    await waitFor(() => {
      expect(screen.queryByText("Late resolved old extraction.")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Use Reviewed Text for Analysis/i })).not.toBeInTheDocument();
    });
  });

  it("removing file while extraction is in flight discards late response", async () => {
    const user = userEvent.setup();
    let resolvePromise: (value: any) => void = () => {};
    const deferred = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    vi.spyOn(api, "extractScreenshot").mockReturnValue(deferred as any);

    render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "test.png", { type: "image/png" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    // Click remove file while in flight
    const removeBtn = screen.getByRole("button", { name: /Remove/i });
    await user.click(removeBtn);

    // Resolve old extraction
    resolvePromise({
      extracted_text: "Late text from deleted image.",
      ocr_language: "eng",
      character_count: 29,
      review_required: true,
      notice: "Please review.",
    });

    await waitFor(() => {
      expect(screen.queryByText("Late text from deleted image.")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Use Reviewed Text for Analysis/i })).not.toBeInTheDocument();
    });
  });

  it("revokes object URL on reset and unmount", async () => {
    const user = userEvent.setup();

    const { unmount } = render(
      <ScreenshotExtractor
        backendState={connectedWithOcr}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("screenshot-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "test.png", { type: "image/png" })] },
    });

    await waitFor(() => {
      expect(screen.getByText("test.png")).toBeInTheDocument();
    });

    // Click remove
    const removeBtn = screen.getByRole("button", { name: /Remove/i });
    await user.click(removeBtn);

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:http://localhost:5173/mock-preview-id");
    expect(screen.queryByText("test.png")).not.toBeInTheDocument();

    unmount();
  });
});
