import React, { useEffect, useMemo, useState } from "react";
import { Case } from "../../types/case";
import { generateCaseSummary } from "./caseSummaryUtils";

export interface CaseSummaryPanelProps {
  currentCase: Case;
}

export const CaseSummaryPanel: React.FC<CaseSummaryPanelProps> = ({ currentCase }) => {
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const summary = useMemo(() => {
    return generateCaseSummary(currentCase, nowMs);
  }, [currentCase, nowMs]);

  if (!summary.hasEvidence) {
    return (
      <div
        data-testid="case-summary-empty"
        className="rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/50 p-6 text-center text-xs text-slate-500 space-y-1"
      >
        <p className="font-semibold text-slate-700">No evidence in case.</p>
        <p>
          Add message analysis, extracted text, or URL inspection findings below to generate an
          evidence-linked case summary.
        </p>
      </div>
    );
  }

  const scrollToEvidence = (e: React.MouseEvent<HTMLAnchorElement>, evidenceId: string) => {
    e.preventDefault();
    const target = document.getElementById(`evidence-item-${evidenceId}`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.focus({ preventScroll: true });
    }
  };

  return (
    <section
      aria-labelledby="case-summary-heading"
      data-testid="case-summary-panel"
      className="rounded-xl border border-teal-200 bg-teal-50/20 p-5 sm:p-6 space-y-6 shadow-sm"
    >
      {/* Summary Header */}
      <div className="border-b border-teal-100 pb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <h3 id="case-summary-heading" className="text-base font-bold text-slate-900 tracking-tight">
              Case Summary
            </h3>
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-teal-100 text-teal-800 border border-teal-300">
              Evidence-Linked
            </span>
          </div>
          <p className="text-xs text-slate-600">
            Synthesized locally from saved evidence items. No external API calls were made.
          </p>
        </div>
        <span className="text-xs font-medium text-slate-500 font-mono">
          Based on {currentCase.evidence.length} evidence item{currentCase.evidence.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-5">
        {/* 1. Warning Signs Section */}
        <div
          data-testid="summary-warning-signs-section"
          className="rounded-lg border border-red-200 bg-white p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-red-600 font-bold" aria-hidden="true">
                ⚠️
              </span>
              <h4 className="text-xs font-bold uppercase tracking-wider text-red-900">
                Warning Signs ({summary.warningSigns.length})
              </h4>
            </div>
            {summary.warningSigns.length > 0 && (
              <span className="text-[11px] font-bold text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded">
                Risk Indicators Identified
              </span>
            )}
          </div>

          {summary.warningSigns.length === 0 ? (
            <p className="text-xs text-slate-500 italic">
              No warning signs identified in current evidence.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {summary.warningSigns.map((sign) => (
                <li
                  key={sign.id}
                  data-testid={`summary-warning-item-${sign.id}`}
                  className="rounded border border-red-100 bg-red-50/40 p-3 text-xs space-y-1.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <strong className="text-slate-900 font-semibold">{sign.title}</strong>
                      {sign.isHistorical && (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded bg-amber-100 text-amber-900 border border-amber-300">
                          Historical (Expired)
                        </span>
                      )}
                    </div>
                    <a
                      href={`#evidence-item-${sign.evidenceId}`}
                      onClick={(e) => scrollToEvidence(e, sign.evidenceId)}
                      className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 border border-teal-200 px-2 py-0.5 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-teal-500"
                    >
                      <span>Evidence: {sign.evidenceTitle}</span>
                      <span aria-hidden="true">&darr;</span>
                    </a>
                  </div>

                  <p className="text-slate-700 leading-relaxed">{sign.detail}</p>

                  {sign.quoteOrUrl && (
                    <div className="pt-0.5">
                      <span className="text-[11px] text-slate-500 block mb-0.5">
                        {sign.sourceType === "url_reputation" || sign.sourceType === "url_structure"
                          ? "Destination URL (Plain Text):"
                          : "Direct Quote (Plain Text):"}
                      </span>
                      {sign.sourceType === "url_reputation" || sign.sourceType === "url_structure" ? (
                        <code
                          data-testid="summary-url-plain"
                          className="font-mono text-[11px] text-slate-800 bg-white border border-slate-200 px-2 py-1 rounded block break-all select-all whitespace-pre-wrap"
                        >
                          {sign.quoteOrUrl}
                        </code>
                      ) : (
                        <blockquote
                          data-testid="summary-quote-plain"
                          className="font-mono text-[11px] text-slate-800 bg-white border border-slate-200 px-2 py-1 rounded block break-words whitespace-pre-wrap select-all"
                        >
                          &ldquo;{sign.quoteOrUrl}&rdquo;
                        </blockquote>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 2. Conflicting Findings Section */}
        <div
          data-testid="summary-conflicts-section"
          className="rounded-lg border border-slate-200 bg-white p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-amber-600 font-bold" aria-hidden="true">
                ⚖️
              </span>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">
                Conflicting Findings ({summary.conflicts.length})
              </h4>
            </div>
          </div>

          {summary.conflicts.length === 0 ? (
            <div className="rounded bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 space-y-1">
              <span className="font-semibold text-slate-700 block">
                No direct conflicts identified in the saved evidence.
              </span>
              <p className="text-slate-500 leading-relaxed text-[11px]">
                (Note: A &ldquo;No Known Threat Matches&rdquo; reputation lookup evaluates threat feed inclusion only
                and does not contradict warning signs in message text.)
              </p>
            </div>
          ) : (
            <ul className="space-y-2.5">
              {summary.conflicts.map((conflict) => (
                <li
                  key={conflict.id}
                  data-testid={`summary-conflict-item-${conflict.id}`}
                  className="rounded border border-amber-200 bg-amber-50/50 p-3 text-xs space-y-2"
                >
                  <div className="font-bold text-amber-950">{conflict.title}</div>
                  <p className="text-amber-900 leading-relaxed">{conflict.description}</p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <span className="text-[11px] font-semibold text-amber-900">Related Evidence:</span>
                    {conflict.evidenceIds.map((id) => (
                      <a
                        key={id}
                        href={`#evidence-item-${id}`}
                        onClick={(e) => scrollToEvidence(e, id)}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900 bg-white border border-teal-200 px-2 py-0.5 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-teal-500"
                      >
                        <span>Evidence #{id.substring(0, 12)}</span>
                        <span aria-hidden="true">&darr;</span>
                      </a>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* Observations Over Time (when same URL has multiple lookups at different times) */}
          {summary.temporalObservations.length > 0 && (
            <div
              data-testid="summary-temporal-observations"
              className="mt-3 rounded border border-blue-200 bg-blue-50/40 p-3 text-xs space-y-2"
            >
              <div className="flex items-center gap-2">
                <span className="text-blue-600 font-bold" aria-hidden="true">
                  ⏱️
                </span>
                <span className="font-bold text-slate-900">
                  Observations Over Time ({summary.temporalObservations.length})
                </span>
              </div>
              <p className="text-slate-600 text-[11px] leading-relaxed">
                Reputation lookups performed at different times reflect updates over time rather than direct conflicts.
              </p>
              <div className="space-y-2 pt-1">
                {summary.temporalObservations.map((obs) => (
                  <div key={obs.id} className="rounded border border-blue-100 bg-white p-2.5 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-1">
                      <span className="text-[11px] font-semibold text-slate-600">Target URL (Plain Text):</span>
                    </div>
                    <code
                      data-testid="summary-temporal-url"
                      className="font-mono text-[11px] text-slate-800 bg-slate-50 border border-slate-200 px-2 py-0.5 rounded block break-all select-all whitespace-pre-wrap"
                    >
                      {obs.url}
                    </code>
                    <ul className="space-y-1.5 pt-1">
                      {obs.observations.map((item) => (
                        <li
                          key={item.evidenceId}
                          data-testid={`temporal-obs-item-${item.evidenceId}`}
                          className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-1 text-[11px]"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-slate-500">Checked: {item.checkedAt}</span>
                            <span
                              className={`px-1.5 py-0.2 rounded font-semibold text-[10px] uppercase tracking-wider border ${
                                item.status === "threat_match"
                                  ? "bg-red-50 text-red-700 border-red-200"
                                  : item.status === "no_known_match"
                                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                  : "bg-amber-50 text-amber-700 border-amber-200"
                              }`}
                            >
                              {item.status.replace(/_/g, " ")}
                            </span>
                            {item.isExpired && (
                              <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded bg-amber-100 text-amber-900 border border-amber-300">
                                Historical (Expired)
                              </span>
                            )}
                          </div>
                          <a
                            href={`#evidence-item-${item.evidenceId}`}
                            onClick={(e) => scrollToEvidence(e, item.evidenceId)}
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 border border-teal-200 px-2 py-0.5 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-teal-500"
                          >
                            <span>Evidence: {item.evidenceTitle}</span>
                            <span aria-hidden="true">&darr;</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 3. What Remains Unknown Section */}
        <div
          data-testid="summary-unknowns-section"
          className="rounded-lg border border-slate-200 bg-white p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-blue-600 font-bold" aria-hidden="true">
                🔍
              </span>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">
                What Remains Unknown ({summary.unknowns.length})
              </h4>
            </div>
            <span className="text-[11px] text-slate-500">Missing, Expired &amp; Unverified Areas</span>
          </div>

          <ul className="space-y-2">
            {summary.unknowns.map((unknown) => (
              <li
                key={unknown.id}
                data-testid={`summary-unknown-item-${unknown.id}`}
                className="rounded border border-slate-200 bg-slate-50/70 p-3 text-xs space-y-1"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="text-slate-900 font-semibold">{unknown.title}</strong>
                  {unknown.evidenceId && (
                    <a
                      href={`#evidence-item-${unknown.evidenceId}`}
                      onClick={(e) => scrollToEvidence(e, unknown.evidenceId!)}
                      className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900 bg-white border border-teal-200 px-2 py-0.5 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-teal-500"
                    >
                      <span>Evidence: {unknown.evidenceTitle}</span>
                      <span aria-hidden="true">&darr;</span>
                    </a>
                  )}
                </div>
                <p className="text-slate-600 leading-relaxed">{unknown.description}</p>
              </li>
            ))}
          </ul>
        </div>

        {/* 4. Practical Verification Steps Section */}
        <div
          data-testid="summary-verification-section"
          className="rounded-lg border border-emerald-200 bg-white p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-emerald-600 font-bold" aria-hidden="true">
                ✅
              </span>
              <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-950">
                Practical Verification Steps ({summary.verificationSteps.length})
              </h4>
            </div>
            <span className="text-[11px] font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
              Recommended Next Actions
            </span>
          </div>

          <ul className="space-y-2">
            {summary.verificationSteps.map((vStep, idx) => (
              <li
                key={vStep.id}
                data-testid={`summary-verification-step-${vStep.id}`}
                className="rounded border border-emerald-100 bg-emerald-50/30 p-3 text-xs space-y-1.5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex items-start gap-2 flex-1">
                    <span className="font-bold text-emerald-800 shrink-0">{idx + 1}.</span>
                    <p className="text-slate-800 leading-relaxed font-medium">{vStep.step}</p>
                  </div>
                  {vStep.sourceEvidenceId && (
                    <a
                      href={`#evidence-item-${vStep.sourceEvidenceId}`}
                      onClick={(e) => scrollToEvidence(e, vStep.sourceEvidenceId!)}
                      className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900 bg-white border border-teal-200 px-2 py-0.5 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-teal-500 shrink-0"
                    >
                      <span>From Evidence</span>
                      <span aria-hidden="true">&darr;</span>
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
};
