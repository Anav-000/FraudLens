import React, { useEffect, useRef, useState } from "react";
import {
  ApiClientError,
  checkUrlReputation,
  inspectUrl,
  previewUrlForReputation,
} from "../../lib/api";
import {
  BackendConnectionState,
  UrlInspectionResponse,
  UrlObservation,
  UrlReputationResponse,
} from "../../types/api";

const MAX_URL_LENGTH = 2048;

interface UrlInspectorProps {
  onInspected?: (result: UrlInspectionResponse) => void;
  backendState?: BackendConnectionState;
  onAddStructureToCase?: (result: UrlInspectionResponse, url: string) => void;
  onAddReputationToCase?: (result: UrlReputationResponse, url: string) => void;
}

export const UrlInspector: React.FC<UrlInspectorProps> = ({
  onInspected,
  backendState,
  onAddStructureToCase,
  onAddReputationToCase,
}) => {
  const [url, setUrl] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [result, setResult] = useState<UrlInspectionResponse | null>(null);
  const [isStale, setIsStale] = useState(false);

  // Phase 4B URL Reputation State
  const [consent, setConsent] = useState(false);
  const [isLoadingReputation, setIsLoadingReputation] = useState(false);
  const [reputationResult, setReputationResult] = useState<UrlReputationResponse | null>(null);
  const [reputationError, setReputationError] = useState<ApiClientError | null>(null);
  const [isReputationStale, setIsReputationStale] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const reputationAbortControllerRef = useRef<AbortController | null>(null);
  const stalenessTimerRef = useRef<NodeJS.Timeout | null>(null);

  const isReputationConfigured =
    backendState?.status === "connected" &&
    backendState.capabilities.url_reputation === true;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (reputationAbortControllerRef.current) {
        reputationAbortControllerRef.current.abort();
      }
      if (stalenessTimerRef.current) {
        clearTimeout(stalenessTimerRef.current);
      }
    };
  }, []);

  // Time-driven staleness timer: automatically marks displayed results stale after expiration deadline,
  // honoring earlier of expires_at and checked_at + 30 min, incoming is_stale, and tab visibility/focus restoration
  useEffect(() => {
    if (!reputationResult) {
      return;
    }

    const computeFreshnessDelay = () => {
      if (reputationResult.is_stale) {
        return 0;
      }
      const checkedAtMs = new Date(reputationResult.checked_at).getTime();
      const maxFreshnessMs = checkedAtMs + 30 * 60 * 1000; // 30-minute Google freshness rule
      let deadlineMs = maxFreshnessMs;
      if (reputationResult.expires_at) {
        const expiresAtMs = new Date(reputationResult.expires_at).getTime();
        if (!isNaN(expiresAtMs)) {
          deadlineMs = Math.min(expiresAtMs, maxFreshnessMs);
        }
      }
      const now = Date.now();
      return Math.max(0, deadlineMs - now);
    };

    const initialDelay = computeFreshnessDelay();
    stalenessTimerRef.current = setTimeout(() => {
      setIsReputationStale(true);
    }, initialDelay);

    const handleVisibilityOrFocus = () => {
      if (document.visibilityState === "visible") {
        const remainingDelay = computeFreshnessDelay();
        if (remainingDelay === 0) {
          setIsReputationStale(true);
        } else {
          if (stalenessTimerRef.current) {
            clearTimeout(stalenessTimerRef.current);
          }
          stalenessTimerRef.current = setTimeout(() => {
            setIsReputationStale(true);
          }, remainingDelay);
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityOrFocus);
    window.addEventListener("focus", handleVisibilityOrFocus);

    return () => {
      if (stalenessTimerRef.current) {
        clearTimeout(stalenessTimerRef.current);
        stalenessTimerRef.current = null;
      }
      document.removeEventListener("visibilitychange", handleVisibilityOrFocus);
      window.removeEventListener("focus", handleVisibilityOrFocus);
    };
  }, [reputationResult]);

  const handleUrlChange = (newUrl: string) => {
    // If an inspection request is in flight and user modifies URL, abort it
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsLoading(false);
    }
    // If a reputation request is in flight, abort it as well
    if (reputationAbortControllerRef.current) {
      reputationAbortControllerRef.current.abort();
      reputationAbortControllerRef.current = null;
      setIsLoadingReputation(false);
    }

    setUrl(newUrl);
    setError(null);
    setReputationError(null);

    // Editing URL invalidates consent and marks previous findings stale
    setConsent(false);
    if (result) {
      setIsStale(true);
    }
    if (reputationResult) {
      setIsReputationStale(true);
    }
  };

  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (reputationAbortControllerRef.current) {
      reputationAbortControllerRef.current.abort();
      reputationAbortControllerRef.current = null;
    }
    if (stalenessTimerRef.current) {
      clearTimeout(stalenessTimerRef.current);
      stalenessTimerRef.current = null;
    }
    setUrl("");
    setResult(null);
    setError(null);
    setIsStale(false);
    setIsLoading(false);

    setConsent(false);
    setReputationResult(null);
    setReputationError(null);
    setIsReputationStale(false);
    setIsLoadingReputation(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setError(null);
    setIsStale(false);

    try {
      const inspectionResult = await inspectUrl(trimmed, controller.signal);
      if (abortControllerRef.current === controller) {
        setResult(inspectionResult);
        if (onInspected) {
          onInspected(inspectionResult);
        }
      }
    } catch (err: unknown) {
      if (abortControllerRef.current === controller) {
        if (err instanceof ApiClientError) {
          if (!err.isAborted) {
            setError(err);
          }
        } else {
          setError(new ApiClientError("An unexpected error occurred during URL inspection."));
        }
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setIsLoading(false);
      }
    }
  };

  const handleCheckReputation = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || !consent || isLoadingReputation) return;

    if (reputationAbortControllerRef.current) {
      reputationAbortControllerRef.current.abort();
    }

    const controller = new AbortController();
    reputationAbortControllerRef.current = controller;

    setIsLoadingReputation(true);
    setReputationError(null);
    setIsReputationStale(false);

    try {
      const rep = await checkUrlReputation(trimmed, consent, controller.signal);
      if (reputationAbortControllerRef.current === controller) {
        setReputationResult(rep);
        if (rep.is_stale) {
          setIsReputationStale(true);
        }
      }
    } catch (err: unknown) {
      if (reputationAbortControllerRef.current === controller) {
        if (err instanceof ApiClientError) {
          if (!err.isAborted) {
            setReputationError(err);
          }
        } else {
          setReputationError(new ApiClientError("An unexpected error occurred during URL reputation check."));
        }
      }
    } finally {
      if (reputationAbortControllerRef.current === controller) {
        reputationAbortControllerRef.current = null;
        setIsLoadingReputation(false);
      }
    }
  };

  const renderObservationBadge = (level: UrlObservation["level"]) => {
    if (level === "caution") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200">
          Caution
        </span>
      );
    }
    if (level === "warning") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-800 border border-red-200">
          Warning
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200">
        Informational
      </span>
    );
  };

  return (
    <section
      aria-labelledby="url-inspection-heading"
      className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-6"
    >
      <div className="border-b border-slate-200 pb-4">
        <h2
          id="url-inspection-heading"
          className="text-lg font-bold text-slate-900 tracking-tight"
        >
          URL Structure Inspection
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          Inspect destination hostnames, subdomains, network ports, and character encoding offline without connecting to the remote server, with optional Google Safe Browsing threat reputation lookup.
        </p>
      </div>

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor="url-inspection-input"
              className="block text-sm font-semibold text-slate-800"
            >
              URL to Inspect
            </label>
            <span
              className={`text-xs font-mono ${
                url.length > MAX_URL_LENGTH ? "text-red-600 font-bold" : "text-slate-500"
              }`}
              aria-live="polite"
            >
              {url.length.toLocaleString()} / {MAX_URL_LENGTH.toLocaleString()} characters
            </span>
          </div>

          <input
            id="url-inspection-input"
            type="text"
            value={url}
            onChange={(e) => handleUrlChange(e.target.value)}
            disabled={isLoading || isLoadingReputation}
            maxLength={MAX_URL_LENGTH + 10}
            placeholder="https://example.com/path"
            aria-describedby="url-input-guidance"
            className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-mono text-slate-900 placeholder-slate-400 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20 disabled:bg-slate-50"
          />

          <p id="url-input-guidance" className="text-xs text-slate-500">
            Explicit <code className="text-slate-700 font-mono">http://</code> or <code className="text-slate-700 font-mono">https://</code> scheme is required. The destination will never be loaded or fetched.
          </p>
        </div>

        {/* Offline Action Buttons */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={isLoading || !url.trim() || url.length > MAX_URL_LENGTH}
            className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? (
              <>
                <svg
                  className="animate-spin -ml-0.5 mr-2 h-4 w-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Inspecting Structure...
              </>
            ) : (
              "Inspect URL"
            )}
          </button>

          {(url || result || error || reputationResult || reputationError || isLoading || isLoadingReputation) && (
            <button
              type="button"
              onClick={handleReset}
              className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-300 disabled:opacity-50 transition-colors"
            >
              Reset
            </button>
          )}
        </div>
      </form>

      {/* Offline Error Callout */}
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-900 space-y-1.5"
        >
          <div className="flex flex-wrap items-center gap-2">
            <strong className="font-bold text-red-900">URL Inspection Failed</strong>
            {error.code && (
              <span className="font-mono text-[11px] bg-red-100 text-red-900 px-1.5 py-0.5 rounded border border-red-200">
                {error.code}{error.reason ? ` (${error.reason})` : ""}
              </span>
            )}
          </div>
          <p className="text-red-800">{error.message}</p>
          {error.action && (
            <p className="text-red-700 italic pt-0.5">Advice: {error.action}</p>
          )}
        </div>
      )}

      {/* Offline Stale Results Notice */}
      {isStale && result && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-md bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900 flex items-center justify-between"
        >
          <span>
            <strong>Input modified:</strong> The URL was changed since the last inspection. Click &ldquo;Inspect URL&rdquo; to re-examine the current input.
          </span>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isLoading || !url.trim()}
            className="ml-3 font-semibold text-amber-900 underline hover:no-underline"
          >
            Re-inspect
          </button>
        </div>
      )}

      {/* Inspection Results Card */}
      {result && (
        <div
          className={`space-y-6 pt-2 transition-opacity ${
            isStale ? "opacity-60" : "opacity-100"
          }`}
          data-testid="url-inspection-results"
        >
          {/* Prominent Destination Host Highlight */}
          <div className="rounded-xl border-2 border-teal-500 bg-teal-50/50 p-5 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-teal-800">
                Actual Destination Hostname
              </div>
              {onAddStructureToCase && (
                <button
                  type="button"
                  onClick={() => onAddStructureToCase(result, url)}
                  className="inline-flex items-center px-2.5 py-1 text-xs font-semibold text-teal-800 bg-white border border-teal-300 rounded hover:bg-teal-50 focus:outline-none focus:ring-2 focus:ring-teal-500 shadow-sm"
                >
                  Add Structural Findings to Case
                </button>
              )}
            </div>
            <div
              data-testid="destination-hostname"
              className="text-xl md:text-2xl font-bold font-mono text-slate-900 break-all select-all"
            >
              {result.hostname_unicode}
            </div>

            {result.is_punycode && (
              <div className="text-xs font-mono text-slate-600">
                ASCII Punycode: <span className="font-semibold text-slate-800">{result.hostname_ascii}</span>
              </div>
            )}

            {result.has_userinfo && (
              <div className="mt-3 p-3 rounded-lg bg-amber-100/80 border border-amber-300 text-xs text-amber-900 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <span>Warning: Userinfo in URL</span>
                </div>
                <p>
                  The credentials or username <code className="font-mono bg-white/70 px-1 py-0.5 rounded">{result.userinfo}</code> appear before the <code className="font-mono">@</code> symbol. In standard web browsers, this is authentication information, <strong>not the destination website</strong>. The browser will navigate to <strong className="font-mono">{result.hostname}</strong>.
                </p>
              </div>
            )}

            {result.is_ip_address && (
              <div className="mt-2 text-xs text-slate-600">
                Direct IP Host: <span className="font-semibold font-mono text-slate-800">IPv{result.ip_version}</span> ({result.ip_scope} scope)
              </div>
            )}
          </div>

          {/* Submitted URL (Plain Text - NEVER A LINK) */}
          <div className="space-y-1.5">
            <span className="text-xs font-semibold text-slate-700">
              Submitted URL (Plain Text)
            </span>
            <div
              className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-slate-800 break-all select-all whitespace-pre-wrap"
              data-testid="submitted-url-plain"
            >
              {result.submitted_url}
            </div>
          </div>

          {/* Breakdown Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="p-3 rounded-lg border border-slate-200 bg-white space-y-1">
              <span className="text-slate-500 font-medium">Scheme &amp; Security</span>
              <div className="font-semibold text-slate-800 flex items-center gap-2">
                <span className="uppercase font-mono">{result.scheme}</span>
                {result.scheme === "https" ? (
                  <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-sans text-[11px]">
                    HTTPS scheme — connection not checked
                  </span>
                ) : (
                  <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-sans text-[11px]">
                    Unencrypted (HTTP)
                  </span>
                )}
              </div>
            </div>

            <div className="p-3 rounded-lg border border-slate-200 bg-white space-y-1">
              <span className="text-slate-500 font-medium">Registrable Domain (eTLD+1)</span>
              <div className="font-semibold font-mono text-slate-800 break-all">
                {result.registrable_domain || (
                  <span className="text-slate-400 font-sans">None (IP Address or Special-Use)</span>
                )}
              </div>
            </div>

            <div className="p-3 rounded-lg border border-slate-200 bg-white space-y-1">
              <span className="text-slate-500 font-medium">Subdomain Structure</span>
              <div className="font-semibold text-slate-800">
                {result.subdomain_count > 0 ? (
                  <span className="font-mono break-all">
                    {result.subdomains.join(".")} ({result.subdomain_count} level{result.subdomain_count === 1 ? "" : "s"})
                  </span>
                ) : (
                  <span className="text-slate-500 font-sans">No subdomains</span>
                )}
              </div>
            </div>

            <div className="p-3 rounded-lg border border-slate-200 bg-white space-y-1">
              <span className="text-slate-500 font-medium">Network Port</span>
              <div className="font-semibold text-slate-800">
                {result.port ? (
                  <span>
                    <code className="font-mono">{result.port}</code>{" "}
                    {result.is_default_port ? "(Default)" : "(Non-Default Port)"}
                  </span>
                ) : (
                  <span>
                    Default (<code className="font-mono">{result.scheme === "https" ? "443" : "80"}</code>)
                  </span>
                )}
              </div>
            </div>

            <div className="p-3 rounded-lg border border-slate-200 bg-white space-y-1 md:col-span-2">
              <span className="text-slate-500 font-medium">Path, Query &amp; Fragment</span>
              <div className="font-mono text-slate-800 break-all space-y-0.5">
                <div>Path: <span className="font-semibold">{result.path}</span></div>
                {result.query && <div>Query: <span className="text-slate-600">?{result.query}</span></div>}
                {result.fragment && <div>Fragment: <span className="text-slate-600">#{result.fragment}</span></div>}
              </div>
            </div>
          </div>

          {/* Structural Observations */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700">
              Structural Observations ({result.observations.length})
            </h3>

            {result.observations.length === 0 ? (
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3.5 text-xs text-slate-600">
                No structural anomalies detected. The URL follows standard conventions for a {result.scheme.toUpperCase()} link.
              </div>
            ) : (
              <div className="space-y-2">
                {result.observations.map((obs) => (
                  <div
                    key={obs.id}
                    className="p-3 rounded-lg border border-slate-200 bg-white space-y-1 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      {renderObservationBadge(obs.level)}
                      <strong className="font-semibold text-slate-900">{obs.title}</strong>
                    </div>
                    <p className="text-slate-700 leading-relaxed pl-0.5">{obs.description}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Offline Inspection Notice & Disclaimers */}
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-2 text-xs text-slate-600">
            <div className="flex items-center gap-1.5 font-semibold text-slate-800">
              <span>{result.notice}</span>
            </div>
            <p className="text-slate-600 leading-relaxed">
              {result.limitation}
            </p>
          </div>
        </div>
      )}

      {/* Phase 4B: External URL Reputation Section (Google Safe Browsing) */}
      <div className="border-t border-slate-200 pt-6 space-y-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-slate-900 tracking-tight">
              External Threat Intelligence: Google Safe Browsing
            </h3>
            <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
              Optional Opt-In
            </span>
          </div>
          <p className="text-xs text-slate-600 mt-1">
            Optionally check this URL against Google Safe Browsing lists to detect reported malware, phishing, or unwanted software destinations.
          </p>
        </div>

        {/* Unconfigured Notice if Safe Browsing is not configured on backend */}
        {backendState?.status === "connected" && !isReputationConfigured && (
          <div
            role="status"
            className="rounded-lg bg-slate-50 border border-slate-200 p-3.5 text-xs text-slate-600 space-y-1"
          >
            <div className="flex items-center gap-1.5 font-semibold text-slate-800">
              <span>Google Safe Browsing Unconfigured on Server</span>
            </div>
            <p>
              External URL reputation checks are currently unavailable because the backend server is not configured with a Safe Browsing API key (SAFE_BROWSING_API_KEY). Local URL structure inspection remains fully available above.
            </p>
          </div>
        )}

        {/* Preview of Transmitted URL and Privacy Disclosure */}
        {url.trim() && (
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 space-y-2 text-xs">
            <span className="font-semibold text-slate-700">Preview of Transmitted URL</span>
            <div
              className="p-2.5 bg-white border border-slate-200 rounded font-mono text-slate-800 break-all select-all whitespace-pre-wrap"
              data-testid="preview-url-plain"
            >
              {previewUrlForReputation(url)}
            </div>
            <p className="text-slate-500 leading-relaxed">
              <strong>Privacy Notice:</strong> Checking reputation transmits the destination URL (including path and query parameters, with fragment stripped) over the internet to Google Safe Browsing API. <em>Do not transmit URLs containing confidential tokens, private access keys, or personal identifiers.</em>
            </p>
          </div>
        )}

        {/* Consent Checkbox & Action Button */}
        <div className="space-y-3">
          <label className="flex items-start gap-2.5 cursor-pointer text-xs text-slate-700">
            <input
              type="checkbox"
              id="reputation-consent-checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              disabled={isLoadingReputation || !url.trim() || !isReputationConfigured}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500 disabled:opacity-50"
            />
            <span>
              I consent to transmitting this destination URL to Google Safe Browsing for external threat intelligence reputation evaluation.
            </span>
          </label>

          <div>
            <button
              type="button"
              onClick={() => handleCheckReputation()}
              disabled={
                isLoadingReputation ||
                !url.trim() ||
                url.length > MAX_URL_LENGTH ||
                !consent ||
                !isReputationConfigured
              }
              className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold text-white bg-slate-800 hover:bg-slate-900 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoadingReputation ? (
                <>
                  <svg className="animate-spin -ml-0.5 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Checking Reputation...
                </>
              ) : (
                "Check Reputation (Safe Browsing)"
              )}
            </button>
          </div>
        </div>

        {/* Reputation Error Callout */}
        {reputationError && (
          <div
            role="alert"
            aria-live="assertive"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-900 space-y-1.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <strong className="font-bold text-red-900">Reputation Check Unavailable</strong>
              {reputationError.code && (
                <span className="font-mono text-[11px] bg-red-100 text-red-900 px-1.5 py-0.5 rounded border border-red-200">
                  {reputationError.code}{reputationError.reason ? ` (${reputationError.reason})` : ""}
                </span>
              )}
            </div>
            <p className="text-red-800">{reputationError.message}</p>
            {reputationError.action && (
              <p className="text-red-700 italic pt-0.5">Advice: {reputationError.action}</p>
            )}
          </div>
        )}

        {/* Reputation Stale Notice */}
        {(isReputationStale || reputationResult?.is_stale) && reputationResult && (
          <div
            role="status"
            aria-live="polite"
            data-testid="reputation-stale-notice"
            className="rounded-md bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900 flex items-center justify-between"
          >
            <span>
              <strong>Reputation Result Expired or Input Modified:</strong> This reputation finding has expired (older than 30 minutes) or the input URL was edited. Re-check reputation for current threat intelligence.
            </span>
            <button
              type="button"
              onClick={() => handleCheckReputation()}
              disabled={isLoadingReputation || !url.trim() || !consent || !isReputationConfigured}
              className="ml-3 font-semibold text-amber-900 underline hover:no-underline disabled:opacity-50"
            >
              Re-check
            </button>
          </div>
        )}

        {/* Reputation Results Display */}
        {reputationResult && (
          <div
            data-testid="reputation-results-card"
            className={`rounded-xl border p-5 space-y-4 text-xs transition-opacity ${
              (isReputationStale || reputationResult?.is_stale) ? "opacity-60 border-amber-300 bg-amber-50/20" : "border-slate-200 bg-white shadow-sm"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-800">Reputation Outcome:</span>
                {reputationResult.status === "threat_match" ? (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full font-bold bg-red-100 text-red-800 border border-red-200">
                    Threat Match Detected
                  </span>
                ) : reputationResult.status === "no_known_match" ? (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full font-bold bg-slate-100 text-slate-800 border border-slate-200">
                    No Known Threat Matches
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full font-bold bg-amber-100 text-amber-800 border border-amber-200">
                    Service Unavailable
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {onAddReputationToCase && (
                  <button
                    type="button"
                    onClick={() => onAddReputationToCase(reputationResult, url)}
                    className="inline-flex items-center px-2.5 py-1 text-xs font-semibold text-purple-700 bg-purple-50 border border-purple-200 rounded hover:bg-purple-100 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  >
                    Add Reputation to Case
                  </button>
                )}
                <span className="text-[11px] text-slate-500 font-mono">
                  Provider: {reputationResult.provider}
                </span>
              </div>
            </div>

            {/* Threat Types if match */}
            {reputationResult.threat_types.length > 0 && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg space-y-1">
                <strong className="text-red-900 font-semibold">Reported Threat Categories:</strong>
                <ul className="list-disc list-inside text-red-800 font-mono text-[11px] pt-1 space-y-0.5">
                  {reputationResult.threat_types.map((tt) => (
                    <li key={tt}>{tt}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Summary */}
            <p className="text-slate-800 leading-relaxed font-medium">
              {reputationResult.summary}
            </p>

            {/* Plain text checked URL */}
            <div className="space-y-1 pt-1">
              <span className="text-slate-500 font-medium">Checked URL (Transmitted to Safe Browsing):</span>
              <div
                data-testid="reputation-checked-url"
                className="p-2 bg-slate-50 border border-slate-200 rounded font-mono text-slate-800 break-all select-all whitespace-pre-wrap"
              >
                {reputationResult.checked_url}
              </div>
            </div>

            {/* Conspicuous Advisory & Attribution (Mandatory per ToS) */}
            <div className="rounded-lg bg-slate-50 border border-slate-200 p-3.5 space-y-2 text-[11px] text-slate-600">
              <p className="italic leading-relaxed">{reputationResult.advisory}</p>
              <div className="flex items-center justify-between text-slate-500 font-semibold pt-1 border-t border-slate-200">
                <span>
                  <a
                    href="https://developers.google.com/safe-browsing/v4/advisory"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline text-teal-700 hover:text-teal-900 focus:outline-none focus:ring-1 focus:ring-teal-500 rounded"
                  >
                    Advisory provided by Google
                  </a>
                </span>
                <span className="font-normal font-mono text-[10px]">
                  Checked: {new Date(reputationResult.checked_at).toLocaleTimeString()}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
};
