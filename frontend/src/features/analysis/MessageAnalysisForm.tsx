import React from "react";
import { BackendConnectionState, Language } from "../../types/api";

const MAX_CHAR_LIMIT = 10000;

interface MessageAnalysisFormProps {
  text: string;
  onTextChange: (newText: string) => void;
  language: Language;
  onLanguageChange: (newLang: Language) => void;
  backendState: BackendConnectionState;
  isLoading: boolean;
  onSubmit: () => void;
  onReset: () => void;
  errorMessage?: string | null;
  errorCode?: string | null;
  errorReason?: string | null;
  errorAction?: string | null;
  onRetryAnalysis?: () => void;
  extractedFromScreenshot?: boolean;
  extractedFromDocument?: boolean;
}

export const MessageAnalysisForm: React.FC<MessageAnalysisFormProps> = ({
  text,
  onTextChange,
  language,
  onLanguageChange,
  backendState,
  isLoading,
  onSubmit,
  onReset,
  errorMessage,
  errorCode,
  errorReason,
  errorAction,
  onRetryAnalysis,
  extractedFromScreenshot = false,
  extractedFromDocument = false,
}) => {
  const isBackendConnected = backendState.status === "connected";
  const hasTextAnalysisCapability =
    isBackendConnected && backendState.capabilities.text_analysis;
  const hasAiConfig =
    isBackendConnected && backendState.capabilities.ai_configuration === "present";

  const charCount = text.length;
  const isOverLimit = charCount > MAX_CHAR_LIMIT;
  const isBlank = text.trim().length === 0;

  const canSubmit =
    hasTextAnalysisCapability &&
    hasAiConfig &&
    !isBlank &&
    !isOverLimit &&
    !isLoading;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit();
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 sm:p-8 space-y-6"
    >
      {/* Explanation Language Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-100">
        <div>
          <label
            htmlFor="language-select"
            className="block text-sm font-semibold text-slate-800"
          >
            Explanation Language
          </label>
          <p className="text-xs text-slate-500 mt-0.5">
            Select the explanation language for the AI risk analysis breakdown.
          </p>
        </div>
        <div
          className="flex items-center gap-2"
          role="group"
          aria-label="Explanation Language selection"
        >
          <button
            type="button"
            onClick={() => onLanguageChange("en")}
            aria-pressed={language === "en"}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
              language === "en"
                ? "bg-teal-50 border-teal-600 text-teal-800"
                : "bg-white border-slate-300 text-slate-600 hover:bg-slate-50"
            }`}
          >
            English
          </button>
          <button
            type="button"
            onClick={() => onLanguageChange("hi")}
            aria-pressed={language === "hi"}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
              language === "hi"
                ? "bg-teal-50 border-teal-600 text-teal-800"
                : "bg-white border-slate-300 text-slate-600 hover:bg-slate-50"
            }`}
          >
            हिन्दी (Hindi)
          </button>
        </div>
      </div>

      {/* Message Input Area */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label
            htmlFor="suspicious-message-input"
            className="block text-sm font-semibold text-slate-800"
          >
            Suspicious Message Text
          </label>
          <span
            className={`text-xs font-mono ${
              isOverLimit ? "text-red-600 font-bold" : "text-slate-500"
            }`}
            aria-live="polite"
          >
            {charCount.toLocaleString()} / {MAX_CHAR_LIMIT.toLocaleString()} characters
          </span>
        </div>

        <textarea
          id="suspicious-message-input"
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          disabled={isLoading}
          rows={7}
          placeholder="Paste the suspicious SMS, WhatsApp message, email body, job offer, or payment request here..."
          aria-describedby="char-limit-help privacy-note submission-notice"
          className="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20 disabled:bg-slate-50 resize-y"
        />

        {isOverLimit && (
          <p id="char-limit-help" className="text-xs text-red-600 font-medium">
            Message exceeds maximum allowed length of 10,000 characters. Please shorten the text.
          </p>
        )}
      </div>

      {/* Error Callout with Manual Retry */}
      {errorMessage && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-900 space-y-2.5"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <strong className="font-bold text-red-900">Analysis Request Failed</strong>
                {errorCode && (
                  <span className="font-mono text-[11px] bg-red-100 text-red-900 px-1.5 py-0.5 rounded border border-red-200">
                    {errorCode}{errorReason ? ` (${errorReason})` : ""}
                  </span>
                )}
              </div>
              <p className="text-red-800">{errorMessage}</p>
              {errorAction && (
                <p className="text-red-700 italic pt-0.5">Advice: {errorAction}</p>
              )}
            </div>
            {onRetryAnalysis && (
              <button
                type="button"
                onClick={onRetryAnalysis}
                disabled={isLoading}
                className="flex-shrink-0 px-3 py-1.5 text-xs font-semibold rounded bg-red-700 text-white hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50"
              >
                Retry Analysis
              </button>
            )}
          </div>
        </div>
      )}

      {/* Notice & Demo Boundary */}
      <div className="space-y-2.5 pt-1">
        {extractedFromScreenshot && (
          <div
            id="ocr-provenance-notice"
            className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-700 flex items-start gap-2.5"
          >
            <span className="font-semibold text-slate-600 flex-shrink-0" aria-hidden="true">📋</span>
            <div>
              <strong className="font-semibold text-slate-800">Screenshot Text Provenance Notice:</strong>
              <p className="mt-0.5 text-slate-600 leading-relaxed">
                Analysis evaluates the submitted reviewed text only. Findings concern textual content,
                not image authenticity, visual tampering, sender identity, or URL reputation.
              </p>
            </div>
          </div>
        )}

        {extractedFromDocument && (
          <div
            id="document-provenance-notice"
            className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-700 flex items-start gap-2.5"
          >
            <span className="font-semibold text-slate-600 flex-shrink-0" aria-hidden="true">📄</span>
            <div>
              <strong className="font-semibold text-slate-800">Document Text Provenance Notice:</strong>
              <p className="mt-0.5 text-slate-600 leading-relaxed">
                Analysis evaluates the submitted reviewed text only. Findings concern textual content,
                not document authenticity, signatures, visual tampering, sender identity, or URL reputation.
              </p>
            </div>
          </div>
        )}

        <div
          id="submission-notice"
          className="rounded-lg bg-teal-50/70 border border-teal-200 p-3 text-xs text-teal-900 flex items-start gap-2.5"
        >
          <span className="font-semibold text-teal-800 flex-shrink-0" aria-hidden="true">ℹ</span>
          <div>
            <strong className="font-semibold">Development Demo — Use Fictional Data Only.</strong>
            <p className="mt-0.5 text-teal-800/90">
              Submitted text is sent to Google Gemini for AI analysis. Do not submit real personal,
              financial, or credential information. Screenshot and PDF document extraction run locally on the backend
              and files are never sent to Google.
            </p>
          </div>
        </div>

        <p id="privacy-note" className="text-xs text-slate-500 leading-normal">
          <strong className="font-medium text-slate-700">Privacy Notice:</strong> FraudLens does not persist
          or save your submitted text to any local database or analytics storage.
        </p>
      </div>

      {/* Action Area */}
      <div className="pt-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-t border-slate-100">
        <div className="text-xs text-slate-500">
          {!isBackendConnected ? (
            <span className="text-slate-600 italic">
              Analyze button is disabled until backend service is online.
            </span>
          ) : !hasTextAnalysisCapability ? (
            <span className="text-slate-600 italic">
              Text analysis capability is currently disabled on the backend.
            </span>
          ) : !hasAiConfig ? (
            <span className="text-amber-700 font-medium">
              AI API key is missing or not configured in backend/.env.
            </span>
          ) : isBlank ? (
            <span className="text-slate-600">Enter a message above to enable analysis.</span>
          ) : isOverLimit ? (
            <span className="text-red-600 font-medium">Shorten message to submit.</span>
          ) : isLoading ? (
            <span className="text-teal-700 font-medium flex items-center gap-2">
              <span className="w-3 h-3 border-2 border-teal-600 border-t-transparent rounded-full animate-spin" />
              Processing analysis with Gemini...
            </span>
          ) : (
            <span className="text-teal-700">Ready to submit.</span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {(text.length > 0 || isLoading) && (
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={onReset}
                className="px-3.5 py-2 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-slate-200 transition-colors"
                title="Clears current text and resets any active analysis. Note: Aborting in browser does not guarantee remote provider cancellation."
              >
                Clear / Reset
              </button>
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="inline-flex items-center justify-center px-6 py-2.5 rounded-lg text-sm font-semibold bg-teal-700 text-white shadow-sm hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-teal-600 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? "Analyzing Message..." : "Analyze Message"}
          </button>
        </div>
      </div>
    </form>
  );
};
