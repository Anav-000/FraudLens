import React from "react";
import { BackendConnectionState } from "../types/api";

interface BackendStatusBannerProps {
  state: BackendConnectionState;
  onRetry: () => void;
  isRetrying: boolean;
}

export const BackendStatusBanner: React.FC<BackendStatusBannerProps> = ({
  state,
  onRetry,
  isRetrying,
}) => {
  if (state.status === "checking") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600 flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
          <span>Connecting to backend service...</span>
        </div>
      </div>
    );
  }

  if (state.status === "unavailable") {
    return (
      <div
        role="alert"
        aria-live="assertive"
        className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
      >
        <div className="flex items-start gap-3">
          <span className="w-2.5 h-2.5 rounded-full bg-red-600 mt-1 flex-shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold text-red-900">Backend service unavailable</p>
            <p className="text-red-700 mt-0.5">{state.errorMessage}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={isRetrying}
          className="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-md bg-white text-red-700 border border-red-300 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm self-start sm:self-auto"
        >
          {isRetrying ? "Retrying..." : "Retry Connection"}
        </button>
      </div>
    );
  }

  // Connected state
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-lg border border-teal-200 bg-teal-50/50 p-4 text-sm text-slate-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
    >
      <div className="flex items-start sm:items-center gap-3">
        <span className="w-2.5 h-2.5 rounded-full bg-teal-600 mt-1 sm:mt-0 flex-shrink-0" aria-hidden="true" />
        <div>
          <span className="font-medium text-slate-900">Backend connected: </span>
          <span className="text-slate-700">FastAPI service is online. </span>
          <span className="text-slate-600">
            (Text analysis capability:{" "}
            <strong className="font-semibold text-slate-800">
              {state.capabilities.text_analysis ? "Ready" : "Not yet implemented in Phase 1"}
            </strong>
            )
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="text-xs font-medium text-teal-800 hover:text-teal-900 underline focus:outline-none focus:ring-2 focus:ring-teal-500 self-start sm:self-auto"
      >
        {isRetrying ? "Checking..." : "Re-check status"}
      </button>
    </div>
  );
};
