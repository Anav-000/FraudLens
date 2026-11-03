import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentExtractor } from "../features/document/DocumentExtractor";
import * as api from "../lib/api";
import { BackendConnectionState, DocumentExtractionResponse } from "../types/api";

describe("DocumentExtractor Component", () => {
  const connectedState: BackendConnectionState = {
    status: "connected",
    capabilities: {
      text_analysis: true,
      screenshot_extraction: true,
      document_extraction: true,
      url_reputation: false,
      saved_cases: false,
      ai_connection: "not_tested",
      ai_configuration: "present",
    },
  };

  const sampleSuccessResponse: DocumentExtractionResponse = {
    combined_text: "URGENT NOTICE: Pay 5000 INR registration fee to claim prize.",
    page_count: 2,
    char_count: 59,
    extraction_method: "embedded_text",
    empty_pages: [],
    warning: null,
    pages: [
      { page_number: 1, has_text: true, char_count: 30 },
      { page_number: 2, has_text: true, char_count: 29 },
    ],
    review_required: true,
    notice: "Analysis evaluates the submitted reviewed text only.",
    limitation: "Extraction evaluates embedded text only.",
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects non-PDF files client-side", async () => {
    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    const txtFile = new File(["dummy text"], "document.txt", { type: "text/plain" });

    fireEvent.change(fileInput, { target: { files: [txtFile] } });

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Unsupported file format/i)).toBeInTheDocument();
    expect(screen.queryByText(/Extract Text/i)).not.toBeInTheDocument();
  });

  it("rejects files exceeding 5 MiB client-side", async () => {
    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    // 6 MiB dummy file
    const oversizedFile = new File([new Uint8Array(6 * 1024 * 1024)], "huge.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, { target: { files: [oversizedFile] } });

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/exceeds the 5 MiB maximum limit/i)).toBeInTheDocument();
  });

  it("completes extraction and requires explicit review confirmation before transfer", async () => {
    const user = userEvent.setup();
    const mockUseExtractedText = vi.fn();
    vi.spyOn(api, "extractDocument").mockResolvedValue(sampleSuccessResponse);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={mockUseExtractedText}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    const pdfFile = new File(["%PDF-dummy"], "notice.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [pdfFile] } });

    expect(screen.getByText("notice.pdf")).toBeInTheDocument();
    const extractButton = screen.getByRole("button", { name: /Extract Text/i });
    await user.click(extractButton);

    await waitFor(() => {
      expect(screen.getByDisplayValue(sampleSuccessResponse.combined_text)).toBeInTheDocument();
    });

    // Transfer button must initially be disabled
    const transferButton = screen.getByRole("button", { name: /Use Reviewed Text for Analysis/i });
    expect(transferButton).toBeDisabled();

    // Check confirmation checkbox
    const reviewCheckbox = screen.getByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    await user.click(reviewCheckbox);

    // Transfer button now enabled
    expect(transferButton).toBeEnabled();
    await user.click(transferButton);

    expect(mockUseExtractedText).toHaveBeenCalledWith(sampleSuccessResponse.combined_text);
  });

  it("shows incomplete extraction warning when some pages have no text", async () => {
    const user = userEvent.setup();
    const warningResponse: DocumentExtractionResponse = {
      ...sampleSuccessResponse,
      page_count: 3,
      empty_pages: [2],
      warning: "Pages 2 contained no extractable text. Extraction may be incomplete. Note: Images, signatures, layout, and image-only text are not evaluated.",
      pages: [
        { page_number: 1, has_text: true, char_count: 30 },
        { page_number: 2, has_text: false, char_count: 0 },
        { page_number: 3, has_text: true, char_count: 29 },
      ],
    };

    vi.spyOn(api, "extractDocument").mockResolvedValue(warningResponse);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["%PDF-dummy"], "doc.pdf", { type: "application/pdf" })] },
    });

    const extractButton = screen.getByRole("button", { name: /Extract Text/i });
    await user.click(extractButton);

    await waitFor(() => {
      expect(screen.getByText(/Incomplete Document Extraction/i)).toBeInTheDocument();
      expect(screen.getByText(/Pages 2 contained no extractable text/i)).toBeInTheDocument();
    });
  });

  it("invalidates review confirmation whenever extracted text is edited", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "extractDocument").mockResolvedValue(sampleSuccessResponse);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["%PDF-dummy"], "invoice.pdf", { type: "application/pdf" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    const reviewCheckbox = await screen.findByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    await user.click(reviewCheckbox);
    expect(reviewCheckbox).toBeChecked();

    const textarea = screen.getByRole("textbox", { name: /Extracted Document Text/i });
    await user.type(textarea, " Correction made by user.");

    // Confirmation must automatically be unchecked
    expect(reviewCheckbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: /Use Reviewed Text for Analysis/i })).toBeDisabled();
  });

  it("requires explicit confirmation before replacing nonempty analysis input", async () => {
    const user = userEvent.setup();
    const mockUseExtractedText = vi.fn();
    vi.spyOn(api, "extractDocument").mockResolvedValue(sampleSuccessResponse);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={mockUseExtractedText}
        hasExistingAnalysisText={true}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["%PDF-dummy"], "doc.pdf", { type: "application/pdf" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    const reviewCheckbox = await screen.findByRole("checkbox", {
      name: /I have reviewed and confirmed the extracted text for accuracy/i,
    });
    await user.click(reviewCheckbox);

    const transferBtn = screen.getByRole("button", { name: /Use Reviewed Text for Analysis/i });
    await user.click(transferBtn);

    // Expect overwrite confirmation prompt
    expect(screen.getByText(/Replace Existing Analysis Input\?/i)).toBeInTheDocument();
    expect(mockUseExtractedText).not.toHaveBeenCalled();

    // Click confirm replace
    const confirmBtn = screen.getByRole("button", { name: /Confirm Replace/i });
    await user.click(confirmBtn);

    expect(mockUseExtractedText).toHaveBeenCalledWith(sampleSuccessResponse.combined_text);
  });

  it("removing file while extraction is in flight discards late response", async () => {
    const user = userEvent.setup();
    let resolveExtraction: (val: DocumentExtractionResponse) => void = () => {};
    const extractionPromise = new Promise<DocumentExtractionResponse>((resolve) => {
      resolveExtraction = resolve;
    });

    vi.spyOn(api, "extractDocument").mockReturnValue(extractionPromise);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["%PDF-dummy"], "late.pdf", { type: "application/pdf" })] },
    });

    const extractBtn = screen.getByRole("button", { name: /Extract Text/i });
    await user.click(extractBtn);

    expect(screen.getByText(/Extracting Text.../i)).toBeInTheDocument();

    // Remove file while in-flight
    const removeBtn = screen.getByRole("button", { name: /Remove File/i });
    await user.click(removeBtn);

    // Resolve old in-flight request afterward
    resolveExtraction(sampleSuccessResponse);
    await Promise.resolve();

    // Must not restore review text or enable transfer
    expect(screen.queryByDisplayValue(sampleSuccessResponse.combined_text)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Use Reviewed Text for Analysis/i })).not.toBeInTheDocument();
  });

  it("late responses cannot overwrite user edits", async () => {
    const user = userEvent.setup();
    let resolveExtraction: (val: DocumentExtractionResponse) => void = () => {};
    const extractionPromise = new Promise<DocumentExtractionResponse>((resolve) => {
      resolveExtraction = resolve;
    });

    vi.spyOn(api, "extractDocument").mockReturnValue(extractionPromise);

    render(
      <DocumentExtractor
        backendState={connectedState}
        onUseExtractedText={vi.fn()}
      />
    );

    const fileInput = document.getElementById("document-file-input") as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["%PDF-dummy"], "edit.pdf", { type: "application/pdf" })] },
    });

    await user.click(screen.getByRole("button", { name: /Extract Text/i }));

    // User types manual edit
    const textarea = screen.queryByRole("textbox", { name: /Extracted Document Text/i });
    if (textarea) {
      await user.type(textarea, "User pre-typed content.");
    }

    // Resolve late extraction
    resolveExtraction(sampleSuccessResponse);
    await Promise.resolve();

    // Review text must not be overwritten if user edited
    expect(screen.queryByDisplayValue(sampleSuccessResponse.combined_text)).not.toBeInTheDocument();
  });
});
