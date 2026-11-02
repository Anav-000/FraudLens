import React, { useEffect, useRef, useState } from "react";
import { BackendStatusBanner } from "./components/BackendStatusBanner";
import { Header } from "./components/Header";
import { PlannedCapabilities } from "./components/PlannedCapabilities";
import { AnalysisResultView } from "./features/analysis/AnalysisResultView";
import { MessageAnalysisForm } from "./features/analysis/MessageAnalysisForm";
import { ScreenshotExtractor } from "./features/screenshot/ScreenshotExtractor";
import { analyzeText, ApiClientError, checkBackendConnection } from "./lib/api";
import { BackendConnectionState, Language, TextAnalysisResponse } from "./types/api";

export const App: React.FC = () => {
  const [backendState, setBackendState] = useState<BackendConnectionState>({
    status: "checking",
  });
  const [isRetryingBackend, setIsRetryingBackend] = useState(false);
  const [text, setText] = useState("");
  const [language, setLanguage] = useState<Language>("en");
  const [extractedFromScreenshot, setExtractedFromScreenshot] = useState(false);

  // Analysis State
  const [isLoadingAnalysis, setIsLoadingAnalysis] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<TextAnalysisResponse | null>(null);
  const [isResultStale, setIsResultStale] = useState(false);
  const [analysisError, setAnalysisError] = useState<{
    message: string;
    code?: string;
    reason?: string;
    action?: string;
  } | null>(null);

  // In-flight request controller reference
  const abortControllerRef = useRef<AbortController | null>(null);

  const runVerification = async () => {
    try {
      const result = await checkBackendConnection();
      setBackendState({
        status: "connected",
        capabilities: result.capabilities,
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Unable to establish connection to backend service.";
      setBackendState({
        status: "unavailable",
        errorMessage: message,
      });
    }
  };

  useEffect(() => {
    let ignore = false;

    async function initialCheck() {
      try {
        const result = await checkBackendConnection();
        if (!ignore) {
          setBackendState({
            status: "connected",
            capabilities: result.capabilities,
          });
        }
      } catch (err: unknown) {
        if (!ignore) {
          const message =
            err instanceof Error ? err.message : "Unable to establish connection to backend service.";
          setBackendState({
            status: "unavailable",
            errorMessage: message,
          });
        }
      }
    }

    initialCheck();

    return () => {
      ignore = true;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const handleRetryBackend = async () => {
    setIsRetryingBackend(true);
    try {
      await runVerification();
    } finally {
      setIsRetryingBackend(false);
    }
  };

  const handleTextChange = (newText: string) => {
    setText(newText);
    setExtractedFromScreenshot(false);
    if (analysisResult !== null) {
      setIsResultStale(true);
    }
    if (analysisError !== null) {
      setAnalysisError(null);
    }
  };

  const handleUseExtractedText = (extractedText: string) => {
    setText(extractedText);
    setExtractedFromScreenshot(true);
    if (analysisResult !== null) {
      setIsResultStale(true);
    }
    if (analysisError !== null) {
      setAnalysisError(null);
    }
  };

  const handleClearScreenshotState = () => {
    setExtractedFromScreenshot(false);
  };

  const handleLanguageChange = (newLang: Language) => {
    setLanguage(newLang);
    if (analysisResult !== null && newLang !== analysisResult.language) {
      setIsResultStale(true);
    }
  };

  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setText("");
    setExtractedFromScreenshot(false);
    setAnalysisResult(null);
    setIsResultStale(false);
    setAnalysisError(null);
    setIsLoadingAnalysis(false);
  };

  const handleClearResult = () => {
    setAnalysisResult(null);
    setIsResultStale(false);
  };

  const handleAnalyze = async () => {
    if (isLoadingAnalysis) return;

    // Abort any prior request if still active
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoadingAnalysis(true);
    setAnalysisError(null);

    try {
      const result = await analyzeText(text, language, controller.signal);
      // Only commit if this controller is still current
      if (abortControllerRef.current === controller) {
        setAnalysisResult(result);
        setIsResultStale(false);
      }
    } catch (err: unknown) {
      if (abortControllerRef.current !== controller) {
        // Request was superseded or cancelled; do not update UI state
        return;
      }
      if (err instanceof ApiClientError && err.isAborted) {
        // Explicitly aborted by user; no error banner needed
        return;
      }

      const clientErr =
        err instanceof ApiClientError
          ? err
          : new ApiClientError(
              err instanceof Error ? err.message : "An unexpected error occurred during analysis."
            );

      setAnalysisError({
        message: clientErr.message,
        code: clientErr.code,
        reason: clientErr.reason,
        action: clientErr.action,
      });
    } finally {
      if (abortControllerRef.current === controller) {
        setIsLoadingAnalysis(false);
        abortControllerRef.current = null;
      }
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      <Header />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Backend Status Notification */}
        <BackendStatusBanner
          state={backendState}
          onRetry={handleRetryBackend}
          isRetrying={isRetryingBackend}
        />

        {/* Phase 3A: Screenshot Text Extraction (Local OCR) */}
        <section aria-labelledby="screenshot-extraction-heading">
          <h2 id="screenshot-extraction-heading" className="sr-only">
            Screenshot Text Extraction
          </h2>
          <ScreenshotExtractor
            backendState={backendState}
            onUseExtractedText={handleUseExtractedText}
            onClearScreenshotState={handleClearScreenshotState}
          />
        </section>

        {/* Phase 2B Interactive Feature: Suspicious Message Input & Analysis */}
        <section aria-labelledby="message-analysis-heading">
          <h2 id="message-analysis-heading" className="sr-only">
            Suspicious Message Assessment
          </h2>
          <MessageAnalysisForm
            text={text}
            onTextChange={handleTextChange}
            language={language}
            onLanguageChange={handleLanguageChange}
            backendState={backendState}
            isLoading={isLoadingAnalysis}
            onSubmit={handleAnalyze}
            onReset={handleReset}
            errorMessage={analysisError?.message}
            errorCode={analysisError?.code}
            errorReason={analysisError?.reason}
            errorAction={analysisError?.action}
            onRetryAnalysis={handleAnalyze}
            extractedFromScreenshot={extractedFromScreenshot}
          />
        </section>

        {/* Analysis Results Display */}
        {analysisResult && (
          <section aria-labelledby="analysis-result-section-heading">
            <h2 id="analysis-result-section-heading" className="sr-only">
              Analysis Findings
            </h2>
            <AnalysisResultView
              result={analysisResult}
              isStale={isResultStale}
              onClear={handleClearResult}
            />
          </section>
        )}

        {/* Informational Context for Planned Workflows */}
        <PlannedCapabilities />
      </main>

      <footer className="border-t border-slate-200 bg-white py-6 px-4 text-center text-xs text-slate-500">
        <p>FraudLens • Independent Portfolio Project by Arnav Kumar • Phase 3A Build</p>
      </footer>
    </div>
  );
};

export default App;
