import React from "react";

export const PlannedCapabilities: React.FC = () => {
  return (
    <section aria-labelledby="planned-capabilities-heading" className="bg-white rounded-xl border border-slate-200 p-6 sm:p-8 space-y-4">
      <div className="border-b border-slate-100 pb-3">
        <h2 id="planned-capabilities-heading" className="text-base font-semibold text-slate-900">
          Planned Roadmap (Upcoming Phases)
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          These workflows are documented here for context and will be implemented incrementally.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
        <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-teal-800">
              Message Categories
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded">
              Active
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">Job, Phishing & Payment</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            Targeted evaluation of remote job offers requesting upfront fees, urgent phishing alerts,
            and unauthorized UPI or payment requests.
          </p>
        </div>

        <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-teal-800">
              Local Extraction
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded">
              Phase 3A / 3B
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">Screenshots & Text PDFs</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            Local OCR text extraction from single PNG/JPEG screenshots and embedded-text extraction from text-based PDFs with human-in-the-loop review. Word docs, scanned-document OCR, and external URL reputation remain planned.
          </p>
        </div>

        <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-teal-800">
              Actionable Guidance
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded">
              Active
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">Bilingual Explanations</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            Clear warning signs, inconsistencies, and practical verification steps in English and Hindi,
            without misleading numerical probabilities or false safe guarantees.
          </p>
        </div>
      </div>
    </section>
  );
};
