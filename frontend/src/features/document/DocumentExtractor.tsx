import React, { useEffect, useRef, useState } from "react";
import { ApiClientError, extractDocument } from "../../lib/api";
import { BackendConnectionState, DocumentExtractionResponse } from "../../types/api";

const MAX_DOCUMENT_FILE_SIZE_BYTES = 5 * 1024 * 1024; // 5 MiB
const MAX_CHAR_LIMIT = 10000;

interface DocumentExtractorProps {
  backendState: BackendConnectionState;
  onUseExtractedText: (text: string) => void;
  onClearDocumentState?: () => void;
  hasExistingAnalysisText?: boolean;
}

export const DocumentExtractor: React.FC<DocumentExtractorProps> = ({
  backendState,
  onUseExtractedText,
  onClearDocumentState,
  hasExistingAnalysisText = false,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractedResponse, setExtractedResponse] = useState<DocumentExtractionResponse | null>(null);
  const [reviewedText, setReviewedText] = useState("");
  const [isReviewConfirmed, setIsReviewConfirmed] = useState(false);
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false);
  const [clientError, setClientError] = useState<{
    message: string;
    code?: string;
    action?: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const userHasEditedRef = useRef<boolean>(false);

  // Clean up in-flight requests on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const isBackendConnected = backendState.status === "connected";

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const handleFileChange = (file: File | null | undefined) => {
    // Invalidate prior in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsExtracting(false);
    userHasEditedRef.current = false;
    setExtractedResponse(null);
    setReviewedText("");
    setIsReviewConfirmed(false);
    setShowOverwriteConfirm(false);
    setClientError(null);

    if (!file) {
      setSelectedFile(null);
      if (onClearDocumentState) onClearDocumentState();
      return;
    }

    // Client-side format check (PDF only)
    const isPdfType = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdfType) {
      setSelectedFile(null);
      setClientError({
        message: "Unsupported file format. Please select a text-based PDF document.",
        code: "UNSUPPORTED_DOCUMENT_FORMAT",
        action: "Select a document ending with .pdf.",
      });
      return;
    }

    // Client-side file size check (5 MiB)
    if (file.size > MAX_DOCUMENT_FILE_SIZE_BYTES) {
      setSelectedFile(null);
      setClientError({
        message: `File size exceeds the 5 MiB maximum limit (${formatFileSize(file.size)} selected).`,
        code: "FILE_TOO_LARGE",
        action: "Please upload a smaller or compressed PDF document.",
      });
      return;
    }

    setSelectedFile(file);
  };

  const handleFileRemove = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsExtracting(false);
    userHasEditedRef.current = false;
    setSelectedFile(null);
    setExtractedResponse(null);
    setReviewedText("");
    setIsReviewConfirmed(false);
    setShowOverwriteConfirm(false);
    setClientError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (onClearDocumentState) {
      onClearDocumentState();
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
    setShowOverwriteConfirm(false);

    try {
      const response = await extractDocument(selectedFile, controller.signal);
      // Ensure controller is still current and user has not typed edits
      if (abortControllerRef.current === controller && !userHasEditedRef.current) {
        setExtractedResponse(response);
        setReviewedText(response.combined_text);
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
              err instanceof Error ? err.message : "Document extraction failed unexpectedly."
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

  const handleSendToAnalysisClick = () => {
    if (!isReviewConfirmed || !reviewedText.trim()) return;

    // Explicit confirmation before replacing nonempty analysis input
    if (hasExistingAnalysisText) {
      setShowOverwriteConfirm(true);
    } else {
      commitTransfer();
    }
  };

  const commitTransfer = () => {
    setShowOverwriteConfirm(false);
    onUseExtractedText(reviewedText);
  };

  const charCount = reviewedText.length;
  const isOverCharLimit = charCount > MAX_CHAR_LIMIT;

  return (
    <div className="bg-slate-50/70 rounded-xl border border-slate-200 p-5 sm:p-6 space-y-5">
      <div className="border-b border-slate-200/80 pb-3">
        <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
          <span>PDF Document Text Extraction</span>
          <span className="text-[10px] font-bold uppercase tracking-wider bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded">
            Phase 3B
          </span>
        </h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Extract embedded text from suspicious letters, invoices, or notices (text-based PDF only, max 5 MiB, max 10 pages).
        </p>
      </div>

      {/* File Dropzone / Picker */}
      <div className="space-y-3">
        <label
          htmlFor="document-file-input"
          className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
        >
          Select PDF Document
        </label>

        {!selectedFile ? (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleFileChange(e.dataTransfer.files[0]);
              }
            }}
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-slate-300 hover:border-indigo-400 bg-white/70 hover:bg-indigo-50/20 rounded-xl p-6 text-center cursor-pointer transition-colors focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-indigo-500"
          >
            <input
              ref={fileInputRef}
              type="file"
              id="document-file-input"
              accept=".pdf,application/pdf"
              className="sr-only"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  handleFileChange(e.target.files[0]);
                }
              }}
              disabled={isExtracting}
            />
            <div className="flex flex-col items-center justify-center space-y-2">
              <div className="w-10 h-10 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <div className="text-xs text-slate-600">
                <span className="font-semibold text-indigo-700 hover:underline">Click to browse</span> or drag and drop a PDF
              </div>
              <p className="text-[11px] text-slate-400">
                Text-based PDF only • Maximum 5 MiB • Maximum 10 pages
              </p>
            </div>
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-lg p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-slate-800 truncate" title={selectedFile.name}>
                  {selectedFile.name}
                </p>
                <p className="text-[11px] text-slate-500">
                  {formatFileSize(selectedFile.size)} • PDF Document
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
              <button
                type="button"
                onClick={handleFileRemove}
                disabled={isExtracting}
                className="px-2.5 py-1.5 text-xs text-slate-600 hover:text-rose-700 hover:bg-rose-50 border border-slate-200 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-rose-500 disabled:opacity-50"
              >
                Remove File
              </button>
              <button
                type="button"
                onClick={handleExtractText}
                disabled={isExtracting || !isBackendConnected}
                className="px-3.5 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 rounded shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 flex items-center gap-1.5"
              >
                {isExtracting ? (
                  <>
                    <svg className="animate-spin -ml-0.5 mr-1 h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>Extracting Text...</span>
                  </>
                ) : (
                  <span>Extract Text</span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Client / Server Error Callout */}
      {clientError && (
        <div
          role="alert"
          className="rounded-lg bg-rose-50 border border-rose-200/80 p-3.5 text-xs text-rose-900 space-y-1.5"
        >
          <div className="flex items-start gap-2">
            <svg className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <div className="font-semibold text-rose-950 flex items-center gap-2">
                <span>Document Extraction Failed</span>
                {clientError.code && (
                  <span className="font-mono text-[10px] bg-rose-100 text-rose-800 px-1.5 py-0.2 rounded border border-rose-200">
                    {clientError.code}
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-rose-800">{clientError.message}</p>
              {clientError.action && (
                <p className="mt-1 font-medium text-rose-900">{clientError.action}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Partial Incomplete Extraction Warning */}
      {extractedResponse && extractedResponse.warning && (
        <div
          role="alert"
          className="rounded-lg bg-amber-50 border border-amber-200 p-3.5 text-xs text-amber-900 flex items-start gap-2.5"
        >
          <svg className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <span className="font-semibold block text-amber-950">Incomplete Document Extraction</span>
            <p className="mt-0.5">{extractedResponse.warning}</p>
          </div>
        </div>
      )}

      {/* Extracted Text Review Area */}
      {reviewedText !== "" && (
        <div className="space-y-3 pt-2 border-t border-slate-200/80">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5">
            <label
              htmlFor="document-review-textarea"
              className="text-xs font-semibold uppercase tracking-wider text-slate-700 flex items-center gap-2"
            >
              <span>Extracted Document Text (Editable)</span>
              {extractedResponse && (
                <span className="text-[11px] font-normal text-slate-500 normal-case">
                  • {extractedResponse.page_count} {extractedResponse.page_count === 1 ? "page" : "pages"}
                </span>
              )}
            </label>
            <div className="text-[11px] text-slate-500">
              <span className={isOverCharLimit ? "font-bold text-rose-600" : "text-slate-600"}>
                {charCount.toLocaleString()}
              </span>
              <span className="text-slate-400"> / {MAX_CHAR_LIMIT.toLocaleString()} chars</span>
            </div>
          </div>

          <textarea
            id="document-review-textarea"
            rows={6}
            value={reviewedText}
            onChange={(e) => handleReviewedTextChange(e.target.value)}
            className={`w-full rounded-lg p-3 text-xs font-mono text-slate-800 bg-white border focus:outline-none focus:ring-2 transition-colors ${
              isOverCharLimit
                ? "border-rose-300 focus:ring-rose-500"
                : "border-slate-300 focus:ring-indigo-500 focus:border-indigo-500"
            }`}
            placeholder="Extracted document text will appear here for your review and correction..."
          />

          {isOverCharLimit && (
            <p className="text-xs font-medium text-rose-600">
              Extracted text exceeds the maximum limit of {MAX_CHAR_LIMIT.toLocaleString()} characters.
              Please crop or shorten the text before confirming.
            </p>
          )}

          {/* Review Rationale & Privacy Notice */}
          <div className="rounded-lg bg-slate-100/90 border border-slate-200/90 p-3 text-xs text-slate-600 space-y-1.5">
            <p className="font-semibold text-slate-800">
              Important: Review and verify before analysis
            </p>
            <p>
              Extraction can alter reading order, spacing, and characters, and may omit content.
              Confirmation is an opportunity to correct errors, not a guarantee of accuracy.
            </p>
            <p className="text-[11px] text-slate-500 pt-0.5">
              Privacy Notice: The PDF stays on the backend during extraction. Reviewed text is sent
              to the AI analysis provider only when you explicitly click "Analyze Message".
            </p>
          </div>

          {/* User Confirmation Checkbox */}
          <div className="pt-1">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                id="document-review-confirm-checkbox"
                checked={isReviewConfirmed}
                onChange={(e) => setIsReviewConfirmed(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-xs text-slate-700 select-none">
                I have reviewed and confirmed the extracted text for accuracy.
              </span>
            </label>
          </div>

          {/* Overwrite Confirmation Modal / Prompt */}
          {showOverwriteConfirm ? (
            <div
              role="alert"
              className="rounded-lg bg-amber-50 border border-amber-300 p-3.5 space-y-2 text-xs text-amber-950"
            >
              <div className="font-semibold flex items-center gap-1.5">
                <svg className="w-4 h-4 text-amber-700 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <span>Replace Existing Analysis Input?</span>
              </div>
              <p className="text-amber-900">
                The analysis form already contains message text. Do you want to replace it with this reviewed document text?
              </p>
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={commitTransfer}
                  className="px-3 py-1.5 bg-amber-700 text-white font-medium rounded hover:bg-amber-800 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500"
                >
                  Confirm Replace
                </button>
                <button
                  type="button"
                  onClick={() => setShowOverwriteConfirm(false)}
                  className="px-3 py-1.5 bg-white text-slate-700 border border-slate-300 font-medium rounded hover:bg-slate-50 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            /* Action Button: Transfer to Analysis */
            <div className="flex items-center justify-end pt-1">
              <button
                type="button"
                onClick={handleSendToAnalysisClick}
                disabled={!isReviewConfirmed || !reviewedText.trim() || isOverCharLimit}
                className="px-4 py-2 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 disabled:cursor-not-allowed rounded-lg shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                Use Reviewed Text for Analysis
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
