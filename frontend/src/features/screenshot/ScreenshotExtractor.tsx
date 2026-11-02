import React, { useEffect, useRef, useState } from "react";
import { ApiClientError, extractScreenshot } from "../../lib/api";
import { BackendConnectionState, OcrLanguage, ScreenshotExtractionResponse } from "../../types/api";

const MAX_IMAGE_FILE_SIZE_BYTES = 5 * 1024 * 1024; // 5 MiB
const MAX_CHAR_LIMIT = 10000;

interface ScreenshotExtractorProps {
  backendState: BackendConnectionState;
  onUseExtractedText: (text: string) => void;
  onClearScreenshotState?: () => void;
}

export const ScreenshotExtractor: React.FC<ScreenshotExtractorProps> = ({
  backendState,
  onUseExtractedText,
  onClearScreenshotState,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [ocrLanguage, setOcrLanguage] = useState<OcrLanguage>("eng");
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractedResponse, setExtractedResponse] = useState<ScreenshotExtractionResponse | null>(null);
  const [reviewedText, setReviewedText] = useState("");
  const [isReviewConfirmed, setIsReviewConfirmed] = useState(false);
  const [clientError, setClientError] = useState<{
    message: string;
    code?: string;
    action?: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const userHasEditedRef = useRef<boolean>(false);
  const previewUrlRef = useRef<string | null>(null);

  // Keep previewUrlRef in sync
  useEffect(() => {
    previewUrlRef.current = previewUrl;
  }, [previewUrl]);

  // Clean up object URL on unmount
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const isBackendConnected = backendState.status === "connected";
  const isOcrAvailable =
    isBackendConnected && Boolean(backendState.capabilities.screenshot_extraction);

  const revokeCurrentPreview = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
  };

  const handleFileChange = (file: File | null | undefined) => {
    // Invalidate prior extraction association and revoke prior preview
    revokeCurrentPreview();
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsExtracting(false);
    userHasEditedRef.current = false;
    setExtractedResponse(null);
    setReviewedText("");
    setIsReviewConfirmed(false);
    setClientError(null);

    if (!file) {
      setSelectedFile(null);
      if (onClearScreenshotState) onClearScreenshotState();
      return;
    }

    // Client-side file type check
    const validTypes = ["image/png", "image/jpeg", "image/jpg"];
    if (!validTypes.includes(file.type.toLowerCase()) && !file.name.match(/\.(png|jpe?g)$/i)) {
      setSelectedFile(null);
      setClientError({
        message: "Unsupported file format. Please select a PNG or JPEG screenshot.",
        code: "INVALID_IMAGE",
        action: "Select an image ending with .png or .jpg/.jpeg.",
      });
      return;
    }

    // Client-side size check (5 MiB)
    if (file.size > MAX_IMAGE_FILE_SIZE_BYTES) {
      setSelectedFile(null);
      setClientError({
        message: `File size (${(file.size / (1024 * 1024)).toFixed(2)} MB) exceeds the 5 MiB maximum limit.`,
        code: "FILE_TOO_LARGE",
        action: "Compress, resize, or crop the screenshot before uploading.",
      });
      return;
    }

    setSelectedFile(file);
    const objectUrl = URL.createObjectURL(file);
    setPreviewUrl(objectUrl);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileChange(e.dataTransfer.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    userHasEditedRef.current = false;
    revokeCurrentPreview();
    setSelectedFile(null);
    setExtractedResponse(null);
    setReviewedText("");
    setIsReviewConfirmed(false);
    setClientError(null);
    setIsExtracting(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (onClearScreenshotState) {
      onClearScreenshotState();
    }
  };

  const handleExtractText = async () => {
    if (!selectedFile || isExtracting) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    userHasEditedRef.current = false;

    setIsExtracting(true);
    setClientError(null);

    try {
      const response = await extractScreenshot(selectedFile, ocrLanguage, controller.signal);
      // Ensure controller is still current and user has not typed edits
      if (abortControllerRef.current === controller && !userHasEditedRef.current) {
        setExtractedResponse(response);
        setReviewedText(response.extracted_text);
        // Review confirmation must be explicitly checked by the user
        setIsReviewConfirmed(false);
      }
    } catch (err: unknown) {
      if (abortControllerRef.current !== controller) {
        return;
      }
      if (err instanceof ApiClientError && err.isAborted) {
        return;
      }
      const apiErr =
        err instanceof ApiClientError
          ? err
          : new ApiClientError(
              err instanceof Error ? err.message : "Extraction failed unexpectedly."
            );
      setClientError({
        message: apiErr.message,
        code: apiErr.code,
        action: apiErr.action,
      });
    } finally {
      if (abortControllerRef.current === controller) {
        setIsExtracting(false);
        abortControllerRef.current = null;
      }
    }
  };

  const handleReviewedTextChange = (newText: string) => {
    userHasEditedRef.current = true;
    setReviewedText(newText);
    // Any change to text invalidates review confirmation
    setIsReviewConfirmed(false);
  };

  const handleOcrLanguageChange = (newLang: OcrLanguage) => {
    if (newLang === ocrLanguage) return;
    setOcrLanguage(newLang);
    // Invalidate in-flight extraction
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsExtracting(false);
    userHasEditedRef.current = false;
    // Changing OCR language invalidates prior extraction and review confirmation
    setExtractedResponse(null);
    setReviewedText("");
    setIsReviewConfirmed(false);
    setClientError(null);
  };

  const handleSendToAnalysis = () => {
    if (!isReviewConfirmed || !reviewedText.trim()) return;
    onUseExtractedText(reviewedText);
  };

  const charCount = reviewedText.length;
  const isOverCharLimit = charCount > MAX_CHAR_LIMIT;

  return (
    <div className="bg-slate-50/70 rounded-xl border border-slate-200 p-5 sm:p-6 space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <span>Screenshot Text Extraction</span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-2 py-0.5 rounded">
              Phase 3A
            </span>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Extract text from suspicious SMS, chat, or email screenshots using OCR on the backend.
          </p>
        </div>

        {/* OCR Language Selector */}
        <div className="flex items-center gap-2" role="group" aria-label="OCR recognition language">
          <span className="text-xs font-medium text-slate-600">OCR Language:</span>
          <button
            type="button"
            onClick={() => handleOcrLanguageChange("eng")}
            aria-pressed={ocrLanguage === "eng"}
            className={`px-2.5 py-1 text-xs font-semibold rounded border transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
              ocrLanguage === "eng"
                ? "bg-teal-50 border-teal-600 text-teal-800"
                : "bg-white border-slate-300 text-slate-600 hover:bg-slate-50"
            }`}
          >
            EN (eng)
          </button>
          <button
            type="button"
            onClick={() => handleOcrLanguageChange("hin")}
            aria-pressed={ocrLanguage === "hin"}
            className={`px-2.5 py-1 text-xs font-semibold rounded border transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
              ocrLanguage === "hin"
                ? "bg-teal-50 border-teal-600 text-teal-800"
                : "bg-white border-slate-300 text-slate-600 hover:bg-slate-50"
            }`}
          >
            HI (hin)
          </button>
        </div>
      </div>

      {/* Honest OCR Availability Callout if unavailable */}
      {!isOcrAvailable && isBackendConnected && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3.5 text-xs text-amber-900 space-y-1"
        >
          <div className="flex items-center gap-2 font-semibold text-amber-900">
            <span aria-hidden="true">⚠️</span>
            <span>Local OCR Engine Unavailable on Server Host</span>
          </div>
          <p className="text-amber-800 leading-relaxed">
            Screenshot text extraction runs locally on the backend, but Tesseract-OCR is not installed
            on the system PATH or standard install paths. Direct text pasting is fully available below.
          </p>
          <p className="text-[11px] text-amber-700 font-mono pt-0.5">
            Windows Setup: Install Tesseract-OCR (v5.x) and add English/Hindi traineddata packs.
          </p>
        </div>
      )}

      {/* File Dropzone & Selection */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        className={`border-2 border-dashed rounded-lg p-5 text-center transition-colors ${
          selectedFile
            ? "border-teal-300 bg-teal-50/20"
            : "border-slate-300 bg-white hover:border-teal-400"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          id="screenshot-file-input"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleFileChange(e.target.files[0]);
            }
          }}
          className="sr-only"
        />

        {!selectedFile ? (
          <div className="space-y-2">
            <div className="text-slate-400 text-3xl" aria-hidden="true">
              🖼️
            </div>
            <div>
              <label
                htmlFor="screenshot-file-input"
                className="inline-flex items-center px-4 py-2 rounded-md text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 cursor-pointer shadow-sm focus-within:ring-2 focus-within:ring-teal-500"
              >
                Choose Screenshot Image
              </label>
              <p className="text-xs text-slate-500 mt-1.5">or drag and drop a screenshot here</p>
            </div>
            <p className="text-[11px] text-slate-400">PNG or JPEG only • Maximum file size 5 MiB</p>
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-3 text-left">
              {previewUrl && (
                <img
                  src={previewUrl}
                  alt="Selected screenshot preview"
                  className="w-16 h-16 object-cover rounded border border-slate-200 shadow-sm"
                />
              )}
              <div>
                <p className="text-xs font-semibold text-slate-800 break-all">{selectedFile.name}</p>
                <p className="text-[11px] text-slate-500">
                  {(selectedFile.size / 1024).toFixed(1)} KB • {selectedFile.type || "image/png"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleReset}
                disabled={isExtracting}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 bg-white border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-50"
              >
                Remove
              </button>
              <button
                type="button"
                onClick={handleExtractText}
                disabled={!isOcrAvailable || isExtracting}
                className="px-4 py-1.5 text-xs font-semibold text-white bg-teal-700 hover:bg-teal-800 rounded disabled:bg-slate-300 disabled:cursor-not-allowed shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                {isExtracting ? "Extracting Text..." : "Extract Text"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Extraction Errors */}
      {clientError && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-lg border border-red-200 bg-red-50 p-3.5 text-xs text-red-900 space-y-1"
        >
          <div className="flex items-center gap-2">
            <strong className="font-semibold text-red-900">Extraction Failed</strong>
            {clientError.code && (
              <span className="font-mono text-[10px] bg-red-100 text-red-900 px-1.5 py-0.5 rounded border border-red-200">
                {clientError.code}
              </span>
            )}
          </div>
          <p className="text-red-800">{clientError.message}</p>
          {clientError.action && (
            <p className="text-red-700 italic pt-0.5">Advice: {clientError.action}</p>
          )}
        </div>
      )}

      {/* Extracted Text Review Area */}
      {extractedResponse && (
        <div className="space-y-3 pt-2 border-t border-slate-200">
          <div className="flex items-center justify-between">
            <label
              htmlFor="extracted-text-review"
              className="text-xs font-semibold text-slate-800 flex items-center gap-2"
            >
              <span>Review Extracted Text</span>
              <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-normal">
                Review Required
              </span>
            </label>
            <span
              className={`text-xs font-mono ${
                isOverCharLimit ? "text-red-600 font-bold" : "text-slate-500"
              }`}
            >
              {charCount.toLocaleString()} / {MAX_CHAR_LIMIT.toLocaleString()} chars
            </span>
          </div>

          <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-900">
            <p className="font-medium">
              ⚠️ OCR may misread names, amounts, URLs, or characters.
            </p>
            <p className="text-amber-800/90 mt-0.5">
              Please review and correct the text below before confirming for analysis.
            </p>
          </div>

          <textarea
            id="extracted-text-review"
            value={reviewedText}
            onChange={(e) => handleReviewedTextChange(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-slate-300 p-3 text-xs text-slate-800 font-sans focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20 resize-y"
            placeholder="Extracted text will appear here for review..."
          />

          {isOverCharLimit && (
            <p className="text-xs text-red-600 font-medium">
              Extracted text exceeds the 10,000-character limit. Please shorten or crop the text.
            </p>
          )}

          {/* User Confirmation Checkbox */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pt-1">
            <label className="flex items-start gap-2.5 text-xs text-slate-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isReviewConfirmed}
                onChange={(e) => setIsReviewConfirmed(e.target.checked)}
                disabled={!reviewedText.trim() || isOverCharLimit}
                className="mt-0.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
              />
              <span className="font-medium">
                I have reviewed and confirmed the extracted text for accuracy.
              </span>
            </label>

            <button
              type="button"
              onClick={handleSendToAnalysis}
              disabled={!isReviewConfirmed || !reviewedText.trim() || isOverCharLimit}
              className="px-4 py-2 text-xs font-semibold rounded bg-teal-700 text-white hover:bg-teal-800 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
            >
              Use Reviewed Text for Analysis
            </button>
          </div>
        </div>
      )}

      {/* Privacy Notice */}
      <div className="pt-2 text-[11px] text-slate-500 border-t border-slate-100 leading-normal">
        <strong className="text-slate-700 font-medium">Privacy Boundary:</strong> Screenshot text
        extraction runs locally on the backend. The image is not sent to the AI provider.
        Reviewed text is sent to Google only when you choose Analyze.
      </div>
    </div>
  );
};
