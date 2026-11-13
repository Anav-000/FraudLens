import React from "react";
import { AssessmentType, CategoryType, TextAnalysisResponse } from "../../types/api";

interface AnalysisResultViewProps {
  result: TextAnalysisResponse;
  isStale?: boolean;
  onClear?: () => void;
  onAddToCase?: (result: TextAnalysisResponse) => void;
  activeCaseName?: string | null;
}

const ASSESSMENT_META: Record<
  AssessmentType,
  {
    badgeLabel: string;
    badgeStyle: string;
    containerBorder: string;
    heading: string;
    description?: string;
  }
> = {
  warning_signs_found: {
    badgeLabel: "Warning Signs Detected",
    badgeStyle: "bg-red-100 text-red-800 border-red-300",
    containerBorder: "border-red-200",
    heading: "Suspicious Patterns Identified",
  },
  no_clear_warning_signs: {
    badgeLabel: "No Clear Warning Signs Found",
    badgeStyle: "bg-slate-100 text-slate-800 border-slate-300",
    containerBorder: "border-slate-200",
    heading: "No Obvious Red Flags in Submitted Text",
    description:
      "Important: This does not prove the message or sender is legitimate. Scammers frequently use subtle, multi-stage, or tailored communications that appear harmless in isolation.",
  },
  insufficient_information: {
    badgeLabel: "Insufficient Information",
    badgeStyle: "bg-amber-100 text-amber-900 border-amber-300",
    containerBorder: "border-amber-200",
    heading: "Message Lacks Context for Assessment",
    description:
      "The submitted text is too brief, incomplete, or ambiguous to evaluate safety accurately. Treat unsolicited contacts with standard caution.",
  },
};

const CATEGORY_LABELS: Record<CategoryType, string> = {
  job: "Job / Employment Offer",
  phishing: "Phishing / Impersonation",
  shopping_payment: "Payment / Shopping / UPI",
  other: "Other / General Message",
  unclear: "Uncategorized / General",
};

export const AnalysisResultView: React.FC<AnalysisResultViewProps> = ({
  result,
  isStale = false,
  onClear,
  onAddToCase,
}) => {
  const meta = ASSESSMENT_META[result.assessment] || ASSESSMENT_META.insufficient_information;

  return (
    <div
      role="region"
      aria-label="Analysis Results"
      className={`bg-white rounded-xl border ${meta.containerBorder} shadow-sm overflow-hidden transition-all`}
    >
      {/* Stale Input Notice */}
      {isStale && (
        <div
          role="status"
          className="bg-amber-50 border-b border-amber-200 px-6 py-2.5 text-xs text-amber-900 flex items-center justify-between gap-4"
        >
          <div className="flex items-center gap-2">
            <span className="font-bold text-amber-700" aria-hidden="true">⚠️</span>
            <span>
              <strong>Text or language was modified.</strong> This assessment reflects previous input.
              Click &ldquo;Analyze Message&rdquo; to re-evaluate.
            </span>
          </div>
        </div>
      )}

      {/* Header with Assessment & Category */}
      <div className="p-6 sm:p-8 border-b border-slate-100 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold border uppercase tracking-wide ${meta.badgeStyle}`}
            >
              {meta.badgeLabel}
            </span>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
              {CATEGORY_LABELS[result.category] || result.category}
            </span>
            <span className="text-xs text-slate-500">
              Explanation: {result.language === "hi" ? "हिन्दी (Hindi)" : "English"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {onAddToCase && (
              <button
                type="button"
                onClick={() => onAddToCase(result)}
                className="inline-flex items-center px-2.5 py-1 text-xs font-semibold text-teal-700 bg-teal-50 border border-teal-200 rounded hover:bg-teal-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                Add to Case
              </button>
            )}
            {onClear && (
              <button
                type="button"
                onClick={onClear}
                className="text-xs font-semibold text-slate-600 hover:text-slate-800 underline focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                Clear Result
              </button>
            )}
          </div>
        </div>

        <div>
          <h3 className="text-lg font-bold text-slate-900">{meta.heading}</h3>
          {meta.description && (
            <div className="mt-2 rounded-lg bg-amber-50/90 border border-amber-200 p-3 text-xs text-amber-900">
              <strong className="font-semibold">Cautionary Notice: </strong>
              {meta.description}
            </div>
          )}
        </div>

        {/* Executive Summary */}
        <div className="pt-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
            Summary
          </h4>
          <p className="text-sm text-slate-800 leading-relaxed bg-slate-50 p-3.5 rounded-lg border border-slate-200">
            {result.summary}
          </p>
        </div>
      </div>

      <div className="p-6 sm:p-8 space-y-6">
        {/* Warning Signs Section */}
        {result.warning_signs.length > 0 && (
          <section aria-labelledby="warning-signs-heading" className="space-y-4">
            <div className="flex items-center gap-2">
              <h4 id="warning-signs-heading" className="text-sm font-bold text-slate-900">
                Identified Warning Signs ({result.warning_signs.length})
              </h4>
            </div>

            <div className="space-y-3">
              {result.warning_signs.map((sign, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-slate-200 bg-slate-50/60 p-4 space-y-2.5"
                >
                  <h5 className="text-sm font-semibold text-slate-900">
                    {idx + 1}. {sign.title}
                  </h5>

                  {/* Quoted Evidence: Strictly rendered as plain text string, NEVER clickable links */}
                  <div className="space-y-1">
                    <span className="text-xs font-medium text-slate-500">
                      Direct Quote from Message:
                    </span>
                    <blockquote className="rounded bg-white border border-slate-200 px-3 py-2 text-xs font-mono text-slate-800 break-words whitespace-pre-wrap select-all">
                      &ldquo;{sign.evidence_quote}&rdquo;
                    </blockquote>
                  </div>

                  <p className="text-xs text-slate-700 leading-relaxed pt-1">
                    <strong className="font-medium text-slate-900">Why this matters: </strong>
                    {sign.explanation}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Verification Steps Section */}
        {result.verification_steps.length > 0 && (
          <section aria-labelledby="verification-steps-heading" className="space-y-3">
            <h4 id="verification-steps-heading" className="text-sm font-bold text-slate-900">
              Practical Verification Steps
            </h4>
            <ol className="list-decimal list-inside space-y-1.5 text-xs text-slate-700 bg-teal-50/40 border border-teal-100 rounded-lg p-4 leading-relaxed">
              {result.verification_steps.map((step, idx) => (
                <li key={idx} className="text-slate-800">
                  <span className="text-slate-800">{step}</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* Uncertainties Section */}
        {result.uncertainties.length > 0 && (
          <section aria-labelledby="uncertainties-heading" className="space-y-3">
            <h4 id="uncertainties-heading" className="text-sm font-bold text-slate-900">
              Analysis Limitations & Uncertainties
            </h4>
            <ul className="list-disc list-inside space-y-1.5 text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-4 leading-relaxed">
              {result.uncertainties.map((item, idx) => (
                <li key={idx}>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Provenance & Disclaimer Footer */}
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-2 text-xs text-slate-500">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 text-[11px] font-medium text-slate-600">
            <span>
              <strong>Analysis Basis: </strong> Submitted text only
            </span>
            <span>
              <strong>External Checks: </strong> None performed
            </span>
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500 pt-1 border-t border-slate-200">
            {result.limitation}
          </p>
        </div>
      </div>
    </div>
  );
};
