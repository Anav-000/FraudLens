import React, { useEffect, useState } from "react";
import { Case, EvidenceItem, EvidencePayload, UrlReputationPayload } from "../../types/case";
import { CaseSummaryPanel } from "./CaseSummaryPanel";

const UrlReputationEvidenceView: React.FC<{ payload: UrlReputationPayload }> = ({ payload }) => {
  const { url, result, expires_at, checked_at, is_stale } = payload;
  const [isExpired, setIsExpired] = useState(is_stale);

  useEffect(() => {
    const checkFreshness = () => {
      if (is_stale) {
        setIsExpired(true);
        return;
      }
      const now = Date.now();
      const checkedTime = new Date(checked_at).getTime();
      const expiryTime = expires_at ? new Date(expires_at).getTime() : NaN;
      if ((!isNaN(expiryTime) && now >= expiryTime) || now >= checkedTime + 30 * 60 * 1000) {
        setIsExpired(true);
      }
    };

    checkFreshness();
    const interval = setInterval(checkFreshness, 1000);
    return () => clearInterval(interval);
  }, [checked_at, expires_at, is_stale]);

  return (
    <div className="space-y-3">
      <div className="p-2 rounded bg-slate-100 text-slate-700 text-xs font-semibold">
        URL Threat Reputation (Google Safe Browsing)
      </div>

      {/* Stale Evidence Indicator */}
      {isExpired && (
        <div
          role="status"
          data-testid="evidence-stale-badge"
          className="rounded-lg bg-amber-50 border border-amber-300 p-2.5 text-xs text-amber-900 font-semibold flex items-center gap-2"
        >
          <span aria-hidden="true">⚠️</span>
          <span>
            Stale Reputation Finding: This threat assessment has expired or was captured over 30 minutes ago.
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-slate-600">Reputation Outcome:</span>
        {result.status === "threat_match" ? (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800 border border-red-200">
            Threat Match Detected
          </span>
        ) : result.status === "no_known_match" ? (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-800 border border-slate-200">
            No Known Threat Matches
          </span>
        ) : (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800 border border-amber-200">
            Service Unavailable
          </span>
        )}
      </div>

      {result.threat_types && result.threat_types.length > 0 && (
        <div className="p-2.5 bg-red-50 border border-red-200 rounded text-xs space-y-1">
          <strong className="text-red-900">Reported Threat Categories:</strong>
          <ul className="list-disc list-inside text-red-800 font-mono text-[11px]">
            {result.threat_types.map((tt) => (
              <li key={tt}>{tt}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-1">
        <span className="text-xs font-medium text-slate-500">Checked URL (Plain Text):</span>
        <div
          data-testid="evidence-reputation-url-plain"
          className="p-2.5 bg-slate-50 border border-slate-200 rounded font-mono text-xs text-slate-800 break-all select-all whitespace-pre-wrap"
        >
          {url}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] text-slate-600">
        <div className="p-2 bg-slate-50 border border-slate-200 rounded">
          <span className="font-medium text-slate-500 block">Checked Timestamp:</span>
          <span className="font-mono">{new Date(checked_at).toLocaleString()}</span>
        </div>
        <div className="p-2 bg-slate-50 border border-slate-200 rounded">
          <span className="font-medium text-slate-500 block">Provider Expiry:</span>
          <span className="font-mono">
            {expires_at ? new Date(expires_at).toLocaleString() : "None (30-min display freshness applies)"}
          </span>
        </div>
      </div>

      {/* Mandatory Non-Guarantee Advisory & Attribution */}
      <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-1.5 text-[11px] text-slate-600">
        <p className="italic leading-relaxed">
          Advisory: No known threat match does not guarantee that a link is safe or legitimate. New phishing and malware campaigns may not yet be indexed.
        </p>
        <div className="pt-1 border-t border-slate-200 text-slate-500 font-medium">
          Data provided by Google Safe Browsing.
        </div>
      </div>
    </div>
  );
};

export interface CaseBuilderProps {
  currentCase: Case | null;
  onCreateCase: (name: string) => void;
  onDeleteCase: () => void;
  onRemoveEvidence: (itemId: string) => void;
}

export const CaseBuilder: React.FC<CaseBuilderProps> = ({
  currentCase,
  onCreateCase,
  onDeleteCase,
  onRemoveEvidence,
}) => {
  const [caseNameInput, setCaseNameInput] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = caseNameInput.trim();
    if (!trimmed) {
      setValidationError("Please enter a case name.");
      return;
    }
    setValidationError(null);
    onCreateCase(trimmed);
    setCaseNameInput("");
  };

  const renderPayload = (payload: EvidencePayload) => {
    switch (payload.sourceType) {
      case "text_analysis": {
        const { submittedText, result } = payload;
        return (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-slate-600">Assessment:</span>
              {result.assessment === "warning_signs_found" ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-red-100 text-red-800 border border-red-200">
                  Warning Signs Detected
                </span>
              ) : result.assessment === "no_clear_warning_signs" ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-slate-100 text-slate-800 border border-slate-200">
                  No Clear Warning Signs Found
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-900 border border-amber-200">
                  Insufficient Information
                </span>
              )}
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                Category: {result.category}
              </span>
            </div>

            <div className="space-y-1">
              <span className="text-xs font-medium text-slate-500">Submitted Message Text (Plain Text):</span>
              <div
                data-testid="evidence-message-text"
                className="p-2.5 bg-slate-50 border border-slate-200 rounded font-mono text-xs text-slate-800 break-words whitespace-pre-wrap select-all"
              >
                {submittedText}
              </div>
            </div>

            {result.warning_signs && result.warning_signs.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-xs font-medium text-slate-500">
                  Warning Signs Identified ({result.warning_signs.length}):
                </span>
                <ul className="space-y-1.5 text-xs text-slate-800">
                  {result.warning_signs.map((sign, idx) => (
                    <li key={idx} className="p-2 bg-slate-50 border border-slate-200 rounded">
                      <strong className="text-slate-900 font-semibold">{sign.title}</strong>
                      <p className="text-slate-600 mt-0.5">{sign.explanation}</p>
                      {sign.evidence_quote && (
                        <blockquote className="mt-1 pl-2 border-l-2 border-slate-300 font-mono text-[11px] text-slate-700 break-words">
                          &ldquo;{sign.evidence_quote}&rdquo;
                        </blockquote>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="text-[11px] text-slate-500 italic pt-1 border-t border-slate-100">
              Analysis Basis: Submitted text only. Does not verify sender identity or guarantee legitimacy.
            </div>
          </div>
        );
      }

      case "extracted_text": {
        const { extractionType, fileName, extractedText } = payload;
        return (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold text-slate-600">Extraction Method:</span>
              <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
                {extractionType === "screenshot" ? "Local OCR (Screenshot)" : "Local PDF Parser (Document)"}
              </span>
              {fileName && (
                <span className="text-slate-500">
                  File: <code className="font-mono">{fileName}</code>
                </span>
              )}
            </div>

            <div className="space-y-1">
              <span className="text-xs font-medium text-slate-500">Extracted &amp; Reviewed Content (Plain Text):</span>
              <div
                data-testid="evidence-extracted-text"
                className="p-2.5 bg-slate-50 border border-slate-200 rounded font-mono text-xs text-slate-800 break-words whitespace-pre-wrap select-all max-h-60 overflow-y-auto"
              >
                {extractedText}
              </div>
            </div>

            <div className="text-[11px] text-slate-500 italic pt-1 border-t border-slate-100">
              Provenance: Text extracted locally on backend and human-reviewed.
            </div>
          </div>
        );
      }

      case "url_structure": {
        const { url, result } = payload;
        return (
          <div className="space-y-3">
            <div className="p-2 rounded bg-slate-100 text-slate-700 text-xs font-semibold">
              URL Structural Inspection (Local Syntax Analysis)
            </div>

            <div className="space-y-1">
              <span className="text-xs font-medium text-slate-500">Evaluated URL (Plain Text):</span>
              <div
                data-testid="evidence-url-structure-plain"
                className="p-2.5 bg-slate-50 border border-slate-200 rounded font-mono text-xs text-slate-800 break-all select-all whitespace-pre-wrap"
              >
                {url}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
              <div className="p-2 bg-slate-50 border border-slate-200 rounded">
                <span className="text-slate-500 font-medium block">Destination Host:</span>
                <span className="font-mono font-semibold text-slate-900 break-all">{result.hostname_unicode || result.hostname}</span>
              </div>
              <div className="p-2 bg-slate-50 border border-slate-200 rounded">
                <span className="text-slate-500 font-medium block">Registrable Domain (eTLD+1):</span>
                <span className="font-mono font-semibold text-slate-900 break-all">
                  {result.registrable_domain || "None (IP Address / Special)"}
                </span>
              </div>
              <div className="p-2 bg-slate-50 border border-slate-200 rounded">
                <span className="text-slate-500 font-medium block">Scheme &amp; Port:</span>
                <span className="font-mono text-slate-900">
                  {result.scheme.toUpperCase()} • Port: {result.port || (result.scheme === "https" ? "443 (default)" : "80 (default)")}
                </span>
              </div>
              <div className="p-2 bg-slate-50 border border-slate-200 rounded">
                <span className="text-slate-500 font-medium block">Observations:</span>
                <span className="text-slate-800">
                  {result.observations.length === 0
                    ? "No structural anomalies detected"
                    : `${result.observations.length} observation(s) recorded`}
                </span>
              </div>
            </div>

            {result.observations.length > 0 && (
              <ul className="space-y-1 text-xs">
                {result.observations.map((obs, idx) => (
                  <li key={idx} className="p-2 bg-slate-50 border border-slate-200 rounded text-slate-700">
                    <strong className="text-slate-900">{obs.title}</strong>: {obs.description}
                  </li>
                ))}
              </ul>
            )}

            <div className="text-[11px] text-slate-500 italic pt-1 border-t border-slate-100">
              Notice: Evaluates syntax only. Does not connect to destination server or check external threat lists.
            </div>
          </div>
        );
      }

      case "url_reputation": {
        return <UrlReputationEvidenceView payload={payload} />;
      }
    }
  };

  const getSourceBadge = (item: EvidenceItem) => {
    switch (item.sourceType) {
      case "text_analysis":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-teal-100 text-teal-800 border border-teal-200">
            Message Analysis
          </span>
        );
      case "extracted_text":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-indigo-100 text-indigo-800 border border-indigo-200">
            Extracted Text
          </span>
        );
      case "url_structure":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-blue-100 text-blue-800 border border-blue-200">
            URL Structure
          </span>
        );
      case "url_reputation":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-purple-100 text-purple-800 border border-purple-200">
            Safe Browsing Reputation
          </span>
        );
    }
  };

  return (
    <section aria-labelledby="case-builder-heading" className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 sm:p-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 id="case-builder-heading" className="text-xl font-bold text-slate-900 tracking-tight">
              Case Builder
            </h2>
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-teal-50 text-teal-700 border border-teal-200">
              MVP
            </span>
          </div>
          <p className="text-xs text-slate-600 mt-1">
            Organize findings from message analysis, extracted text, and URL inspections into an in-memory case report.
          </p>
        </div>

        {currentCase && (
          <button
            type="button"
            onClick={onDeleteCase}
            className="px-3 py-1.5 text-xs font-semibold text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors self-start sm:self-auto focus:outline-none focus:ring-2 focus:ring-red-500"
          >
            Delete Case
          </button>
        )}
      </div>

      {/* Case In-Memory Warning */}
      <div
        role="status"
        className="rounded-lg bg-blue-50 border border-blue-200 p-3.5 text-xs text-blue-900 space-y-1"
      >
        <div className="flex items-center gap-2 font-semibold">
          <span aria-hidden="true">ℹ️</span>
          <span>In-Memory Storage Only</span>
        </div>
        <p className="text-blue-800 leading-relaxed">
          Cases and evidence are held in browser memory only. <strong>Refreshing or closing this page clears all case data.</strong> Saving evidence does not make any network requests.
        </p>
      </div>

      {/* No Active Case: Creation Form */}
      {!currentCase ? (
        <form onSubmit={handleCreateSubmit} className="space-y-4 max-w-lg">
          <div className="space-y-1.5">
            <label htmlFor="case-name-input" className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
              Create a New Case
            </label>
            <div className="flex gap-2">
              <input
                id="case-name-input"
                type="text"
                value={caseNameInput}
                onChange={(e) => {
                  setCaseNameInput(e.target.value);
                  if (validationError) setValidationError(null);
                }}
                placeholder="e.g., Suspicious Telegram Job Offer"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20"
              />
              <button
                type="submit"
                className="px-4 py-2 text-xs font-semibold text-white bg-teal-700 hover:bg-teal-800 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors shrink-0"
              >
                Create Case
              </button>
            </div>
            {validationError && (
              <p className="text-xs text-red-600 font-medium">{validationError}</p>
            )}
          </div>
          <p className="text-[11px] text-slate-500">
            Give your case a descriptive name to start collecting evidence from message analysis, extracted text, and URL inspections.
          </p>
        </form>
      ) : (
        /* Active Case View */
        <div className="space-y-6">
          <div className="p-4 bg-slate-50 rounded-lg border border-slate-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase text-slate-500">Active Case:</span>
                <h3 className="text-sm font-bold text-slate-900 break-words" data-testid="active-case-name">
                  {currentCase.name}
                </h3>
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">
                Created: {new Date(currentCase.createdAt).toLocaleString()}
              </div>
            </div>

            <div className="text-xs font-semibold text-slate-700 bg-white px-3 py-1.5 rounded border border-slate-200 self-start sm:self-auto">
              {currentCase.evidence.length} evidence item{currentCase.evidence.length === 1 ? "" : "s"}
            </div>
          </div>

          {/* Evidence-Linked Case Summary Panel */}
          <CaseSummaryPanel currentCase={currentCase} />

          {/* Evidence List */}
          <div className="space-y-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
              Evidence Items ({currentCase.evidence.length})
            </h4>

            {currentCase.evidence.length === 0 ? (
              <div
                data-testid="no-evidence-message"
                className="rounded-lg border-2 border-dashed border-slate-200 p-8 text-center text-xs text-slate-500 space-y-1"
              >
                <p className="font-semibold text-slate-700">No evidence items added yet.</p>
                <p>
                  Use the tools below (Message Analysis, Screenshot Extraction, Document Extraction, or URL Inspector) and click &ldquo;Add to Case&rdquo; to collect evidence.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {currentCase.evidence.map((item) => (
                  <div
                    key={item.id}
                    id={`evidence-item-${item.id}`}
                    data-testid={`evidence-item-${item.id}`}
                    className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5 shadow-sm space-y-3 scroll-mt-6"
                    tabIndex={-1}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {getSourceBadge(item)}
                        <span className="text-xs font-bold text-slate-800">{item.title}</span>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="text-[11px] text-slate-400 font-mono">
                          Added: {new Date(item.addedAt).toLocaleTimeString()}
                        </span>
                        <button
                          type="button"
                          onClick={() => onRemoveEvidence(item.id)}
                          aria-label={`Remove evidence ${item.title}`}
                          className="text-xs font-medium text-red-600 hover:text-red-800 underline focus:outline-none focus:ring-1 focus:ring-red-500 rounded"
                        >
                          Remove Item
                        </button>
                      </div>
                    </div>

                    {renderPayload(item.payload)}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
};
