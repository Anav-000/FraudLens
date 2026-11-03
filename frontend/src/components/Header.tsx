import React from "react";

export const Header: React.FC = () => {
  return (
    <header className="border-b border-slate-200 bg-white py-6 px-4 sm:px-6 lg:px-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-3.5 h-3.5 rounded-full bg-teal-600 inline-block" aria-hidden="true" />
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                FraudLens
              </h1>
            </div>
            <p className="mt-1 text-base font-medium text-teal-800">
              “Spot the warning signs. Verify your next step.”
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-teal-100 text-teal-800 border border-teal-200 w-fit">
              Text Analysis Active
            </span>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-teal-100 text-teal-800 border border-teal-200 w-fit">
              PDF Text Extraction Available
            </span>
          </div>
        </div>
        <p className="mt-3 text-sm text-slate-600 max-w-3xl leading-relaxed">
          FraudLens provides evidence-linked analysis for suspicious text messages (SMS, chat messages, emails, and job offers) to identify concrete warning signs and safe verification steps before sharing sensitive details or sending funds.
        </p>
        <p className="mt-1 text-xs text-slate-500 italic">
          Text-based PDF extraction is available. Scanned-PDF OCR, Word document parsing (.docx), and external URL reputation checks are planned capabilities and not currently available.
        </p>
      </div>
    </header>
  );
};
