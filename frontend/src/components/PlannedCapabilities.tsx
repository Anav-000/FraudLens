import React from "react";

export const PlannedCapabilities: React.FC = () => {
  return (
    <section aria-labelledby="planned-capabilities-heading" className="bg-white rounded-xl border border-slate-200 p-6 sm:p-8 space-y-4">
      <div className="border-b border-slate-100 pb-3">
        <h2 id="planned-capabilities-heading" className="text-base font-semibold text-slate-900">
          Planned Roadmap &amp; Capabilities
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          These workflows are documented here for context and are implemented incrementally.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
        <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-teal-800">
              Message Analysis
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded">
              Active
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">Job, Phishing &amp; Payment</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            Targeted evaluation of remote job offers requesting upfront fees, urgent phishing alerts,
            and unauthorized UPI or payment requests with verbatim evidence quotes.
          </p>
        </div>

        <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-teal-800">
              Local Inspection
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded">
              Active
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">URL Structure Inspection</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            Offline parsing of destination hostnames, PSL registrable domains, userinfo, IP addresses, and punycode. External reputation queries and live DNS lookups remain planned.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
              Future Extensions
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-200 text-slate-700 px-1.5 py-0.5 rounded">
              Planned
            </span>
          </div>
          <h3 className="text-sm font-semibold text-slate-800">External Threat Intel &amp; Scans</h3>
          <p className="text-xs text-slate-600 leading-relaxed">
            External domain reputation services, live threat feeds, scanned-PDF OCR, and Word document parsing (.docx) are planned for future increments.
          </p>
        </div>
      </div>
    </section>
  );
};
