import React, { useEffect, useRef, useState } from "react";
import { BackendStatusBanner } from "./components/BackendStatusBanner";
import { Header } from "./components/Header";
import { PlannedCapabilities } from "./components/PlannedCapabilities";
import { AnalysisResultView } from "./features/analysis/AnalysisResultView";
import { MessageAnalysisForm } from "./features/analysis/MessageAnalysisForm";
import { ScreenshotExtractor } from "./features/screenshot/ScreenshotExtractor";
import { DocumentExtractor } from "./features/document/DocumentExtractor";
import { UrlInspector } from "./features/url/UrlInspector";
import { CaseBuilder } from "./features/case/CaseBuilder";
import { analyzeText, ApiClientError, checkBackendConnection } from "./lib/api";
import {
  BackendConnectionState,
  Language,
  TextAnalysisResponse,
  UrlInspectionResponse,
  UrlReputationResponse,
} from "./types/api";
import { Case, EvidenceItem } from "./types/case";

export type TextProvenance = "none" | "screenshot" | "document";

export const App: React.FC = () => {
  const [backendState, setBackendState] = useState<BackendConnectionState>({
    status: "checking",
  });
  const [isRetryingBackend, setIsRetryingBackend] = useState(false);
  const [text, setText] = useState("");
  const [language, setLanguage] = useState<Language>("en");
  // Single mutually exclusive provenance state: guarantees screenshot and document provenance
  // cannot both remain active after switching input source.
  const [textProvenance, setTextProvenance] = useState<TextProvenance>("none");
  const extractedFromScreenshot = textProvenance === "screenshot";
  const extractedFromDocument = textProvenance === "document";

  // In-Memory Case Builder State
  const [activeCase, setActiveCase] = useState<Case | null>(null);

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
    setTextProvenance("none");
    if (analysisResult) {
      setIsResultStale(true);
    }
  };

  const handleLanguageChange = (newLang: Language) => {
    setLanguage(newLang);
    if (analysisResult) {
      setIsResultStale(true);
    }
  };

  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setText("");
    setTextProvenance("none");
    setAnalysisResult(null);
    setIsResultStale(false);
    setAnalysisError(null);
    setIsLoadingAnalysis(false);
  };

  const handleClearResult = () => {
    setAnalysisResult(null);
    setIsResultStale(false);
  };

  const handleUseExtractedText = (extractedText: string) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setText(extractedText);
    setTextProvenance("screenshot");
    setAnalysisError(null);
    setIsLoadingAnalysis(false);
    if (analysisResult) {
      setIsResultStale(true);
    }
  };

  const handleClearScreenshotState = () => {
    if (textProvenance === "screenshot") {
      setTextProvenance("none");
    }
  };

  const handleUseExtractedDocumentText = (extractedText: string) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setText(extractedText);
    setTextProvenance("document");
    setAnalysisError(null);
    setIsLoadingAnalysis(false);
    if (analysisResult) {
      setIsResultStale(true);
    }
  };

  const handleClearDocumentState = () => {
    if (textProvenance === "document") {
      setTextProvenance("none");
    }
  };

  // Case Builder Handlers
  const handleCreateCase = (name: string) => {
    setActiveCase({
      id: `case-${Date.now()}`,
      name,
      createdAt: new Date().toISOString(),
      evidence: [],
    });
  };

  const handleDeleteCase = () => {
    setActiveCase(null);
  };

  const handleReopenCase = (reopenedCase: Case) => {
    setActiveCase(reopenedCase);
  };

  const handleRemoveEvidence = (itemId: string) => {
    setActiveCase((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        evidence: prev.evidence.filter((item) => item.id !== itemId),
      };
    });
  };

  const handleAddEvidenceItem = (item: Omit<EvidenceItem, "id" | "addedAt">) => {
    const newItem: EvidenceItem = {
      ...item,
      id: `evidence-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
      addedAt: new Date().toISOString(),
    };
    setActiveCase((prev) => {
      if (!prev) {
        return {
          id: `case-${Date.now()}`,
          name: "Untitled Investigation Case",
          createdAt: new Date().toISOString(),
          evidence: [newItem],
        };
      }
      return {
        ...prev,
        evidence: [...prev.evidence, newItem],
      };
    });
  };

  const handleAddAnalysisToCase = (result: TextAnalysisResponse) => {
    handleAddEvidenceItem({
      sourceType: "text_analysis",
      title: "Suspicious Message Analysis",
      payload: {
        sourceType: "text_analysis",
        submittedText: text,
        result,
      },
    });
  };

  const handleAddScreenshotTextToCase = (extractedText: string, fileName?: string) => {
    handleAddEvidenceItem({
      sourceType: "extracted_text",
      title: "Screenshot Extracted Text",
      payload: {
        sourceType: "extracted_text",
        extractionType: "screenshot",
        fileName,
        extractedText,
      },
    });
  };

  const handleAddDocumentTextToCase = (extractedText: string, fileName?: string) => {
    handleAddEvidenceItem({
      sourceType: "extracted_text",
      title: "Document Extracted Text",
      payload: {
        sourceType: "extracted_text",
        extractionType: "document",
        fileName,
        extractedText,
      },
    });
  };

  const handleAddUrlStructureToCase = (result: UrlInspectionResponse, urlString: string) => {
    handleAddEvidenceItem({
      sourceType: "url_structure",
      title: `URL Structure (${result.hostname})`,
      payload: {
        sourceType: "url_structure",
        url: urlString,
        result,
      },
    });
  };

  const handleAddUrlReputationToCase = (result: UrlReputationResponse, urlString: string) => {
    handleAddEvidenceItem({
      sourceType: "url_reputation",
      title: `Safe Browsing: ${result.status === "threat_match" ? "Threat Match" : "No Known Match"}`,
      payload: {
        sourceType: "url_reputation",
        url: urlString,
        result,
        expires_at: result.expires_at ?? null,
        checked_at: result.checked_at,
        is_stale: result.is_stale,
      },
    });
  };

  const handleAnalyze = async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoadingAnalysis(true);
    setAnalysisError(null);

    try {
      const response = await analyzeText(trimmed, language, controller.signal);
      setAnalysisResult(response);
      setIsResultStale(false);
    } catch (err: unknown) {
      if (err instanceof ApiClientError && err.isAborted) {
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

        {/* Case Builder (In-Memory Investigative Case) */}
        <CaseBuilder
          currentCase={activeCase}
          onCreateCase={handleCreateCase}
          onDeleteCase={handleDeleteCase}
          onRemoveEvidence={handleRemoveEvidence}
          onReopenCase={handleReopenCase}
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
            onAddToCase={handleAddScreenshotTextToCase}
          />
        </section>

        {/* Phase 3B: PDF Document Text Extraction (Local pypdf) */}
        <section aria-labelledby="document-extraction-heading">
          <h2 id="document-extraction-heading" className="sr-only">
            PDF Document Text Extraction
          </h2>
          <DocumentExtractor
            backendState={backendState}
            onUseExtractedText={handleUseExtractedDocumentText}
            onClearDocumentState={handleClearDocumentState}
            hasExistingAnalysisText={Boolean(text.trim())}
            onAddToCase={handleAddDocumentTextToCase}
          />
        </section>

        {/* Phase 4A/4B: Local URL Structure Inspection & Reputation */}
        <UrlInspector
          backendState={backendState}
          onAddStructureToCase={handleAddUrlStructureToCase}
          onAddReputationToCase={handleAddUrlReputationToCase}
        />

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
            extractedFromDocument={extractedFromDocument}
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
              onAddToCase={handleAddAnalysisToCase}
            />
          </section>
        )}

        {/* Informational Context for Planned Workflows */}
        <PlannedCapabilities />
      </main>

      <footer className="border-t border-slate-200 bg-white py-6 px-4 text-center text-xs text-slate-500">
        <p>FraudLens • Independent Portfolio Project by Arnav Kumar • Phase 4B Build</p>
      </footer>
    </div>
  );
};

export default App;
