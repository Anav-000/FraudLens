import {
  Case,
  ExtractedTextPayload,
  TextAnalysisPayload,
  UrlReputationPayload,
  UrlStructurePayload,
} from "../../types/case";
import { generateCaseSummary, isReputationExpired } from "./caseSummaryUtils";

function formatSourceType(sourceType: string): string {
  switch (sourceType) {
    case "text_analysis":
      return "Suspicious Message Analysis";
    case "extracted_text":
      return "Extracted Text Content";
    case "url_structure":
      return "URL Structure Inspection";
    case "url_reputation":
      return "URL Threat Reputation (Google Safe Browsing)";
    default:
      return sourceType;
  }
}

/**
 * Generates a clean, plain-text UTF-8 investigation report from the active Case.
 * No API requests or storage modifications are performed.
 */
export function generateCaseReportText(currentCase: Case, nowMs: number = Date.now()): string {
  const summary = generateCaseSummary(currentCase, nowMs);
  const exportIso = new Date(nowMs).toISOString();

  // Map each evidence item ID to its 1-based index in the case
  const evidenceIndexMap = new Map<string, number>();
  currentCase.evidence.forEach((item, idx) => {
    evidenceIndexMap.set(item.id, idx + 1);
  });

  const lines: string[] = [];
  const dividerDouble = "=".repeat(80);
  const dividerSingle = "-".repeat(80);

  // 1. Header & Case Metadata
  lines.push(dividerDouble);
  lines.push("FRAUDLENS CASE INVESTIGATION REPORT");
  lines.push(dividerDouble);
  lines.push(`Case Name:      ${currentCase.name}`);
  lines.push(`Case Created:   ${currentCase.createdAt}`);
  lines.push(`Exported At:    ${exportIso}`);
  lines.push(`Evidence Items: ${currentCase.evidence.length}`);
  lines.push("");
  lines.push("CONFIDENTIALITY & SENSITIVITY NOTICE:");
  lines.push("This report was generated locally in the browser from your active investigation");
  lines.push("case. It contains saved evidence items in plain text, which may include sensitive");
  lines.push("personal, credential, or financial details. Handle and store this file securely.");
  lines.push(dividerDouble);
  lines.push("");

  // 2. Warning Signs
  lines.push(dividerSingle);
  lines.push("1. WARNING SIGNS");
  lines.push(dividerSingle);
  if (summary.warningSigns.length === 0) {
    lines.push("No warning signs identified in current evidence.");
  } else {
    summary.warningSigns.forEach((sign, idx) => {
      const evIdx = evidenceIndexMap.get(sign.evidenceId);
      const evRef = evIdx ? `Evidence #${evIdx}: ${sign.evidenceTitle}` : sign.evidenceTitle;
      lines.push(`[Warning Sign ${idx + 1}] ${sign.title}`);
      if (sign.isHistorical) {
        lines.push("  Status:               [HISTORICAL CONTEXT - EXPIRED]");
      }
      lines.push(`  Evidence Reference:   ${evRef}`);
      lines.push(`  Detail:               ${sign.detail}`);
      if (sign.quoteOrUrl) {
        const label =
          sign.sourceType === "url_reputation" || sign.sourceType === "url_structure"
            ? "Destination URL (Plain Text):"
            : "Evidence Quote (Plain Text):";
        lines.push(`  ${label} ${sign.quoteOrUrl}`);
      }
      lines.push("");
    });
  }
  lines.push("");

  // 3. Conflicting Findings
  lines.push(dividerSingle);
  lines.push("2. CONFLICTING FINDINGS");
  lines.push(dividerSingle);
  if (summary.conflicts.length === 0) {
    lines.push("No direct conflicts identified in the saved evidence.");
    lines.push("(Note: A 'No Known Threat Matches' reputation lookup evaluates threat feed inclusion only");
    lines.push("and does not contradict warning signs in message text or structural URL inspection.)");
  } else {
    summary.conflicts.forEach((conflict, idx) => {
      lines.push(`[Conflict ${idx + 1}] ${conflict.title}`);
      lines.push(`  Description:          ${conflict.description}`);
      const relatedRefs = conflict.evidenceIds.map((id) => {
        const evIdx = evidenceIndexMap.get(id);
        const evItem = currentCase.evidence.find((e) => e.id === id);
        return evIdx ? `Evidence #${evIdx} (${evItem?.title || id})` : `Evidence #${id}`;
      });
      lines.push(`  Related Evidence:     ${relatedRefs.join(", ")}`);
      lines.push("");
    });
  }

  // Observations Over Time (sequential lookups for same destination)
  if (summary.temporalObservations.length > 0) {
    lines.push("");
    lines.push("OBSERVATIONS OVER TIME (MULTIPLE LOOKUPS AT DIFFERENT TIMESTAMPS):");
    lines.push("Reputation lookups performed at different times reflect threat feed updates over time");
    lines.push("rather than direct conflicts.");
    summary.temporalObservations.forEach((obs) => {
      lines.push(`Target URL (Plain Text): ${obs.url}`);
      obs.observations.forEach((item) => {
        const evIdx = evidenceIndexMap.get(item.evidenceId);
        const evRef = evIdx ? `Evidence #${evIdx}` : item.evidenceTitle;
        const statusText = item.status.replace(/_/g, " ").toUpperCase();
        const expTag = item.isExpired ? " [HISTORICAL CONTEXT - EXPIRED]" : "";
        lines.push(`  - Checked: ${item.checkedAt} | Status: ${statusText}${expTag} (${evRef})`);
      });
    });
  }
  lines.push("");

  // 4. What Remains Unknown
  lines.push(dividerSingle);
  lines.push("3. WHAT REMAINS UNKNOWN");
  lines.push(dividerSingle);
  if (summary.unknowns.length === 0) {
    lines.push("No specific unknowns identified.");
  } else {
    summary.unknowns.forEach((unknown, idx) => {
      lines.push(`[Unknown ${idx + 1}] ${unknown.title}`);
      lines.push(`  Description:          ${unknown.description}`);
      if (unknown.evidenceId) {
        const evIdx = evidenceIndexMap.get(unknown.evidenceId);
        const evRef = evIdx ? `Evidence #${evIdx}: ${unknown.evidenceTitle}` : unknown.evidenceTitle;
        lines.push(`  Source Evidence:      ${evRef}`);
      }
      lines.push("");
    });
  }
  lines.push("");

  // 5. Practical Verification Steps
  lines.push(dividerSingle);
  lines.push("4. PRACTICAL VERIFICATION STEPS");
  lines.push(dividerSingle);
  summary.verificationSteps.forEach((vStep, idx) => {
    lines.push(`${idx + 1}. ${vStep.step}`);
    if (vStep.sourceEvidenceId) {
      const evIdx = evidenceIndexMap.get(vStep.sourceEvidenceId);
      const evRef = evIdx
        ? `Evidence #${evIdx}: ${vStep.sourceEvidenceTitle}`
        : vStep.sourceEvidenceTitle;
      lines.push(`   (Derived from ${evRef})`);
    }
  });
  lines.push("");

  // 6. Numbered Evidence References
  lines.push(dividerSingle);
  lines.push("5. NUMBERED EVIDENCE REFERENCES");
  lines.push(dividerSingle);
  if (currentCase.evidence.length === 0) {
    lines.push("No evidence items in case.");
  } else {
    currentCase.evidence.forEach((item, idx) => {
      const evidenceNum = idx + 1;
      lines.push(`Evidence #${evidenceNum}: [${formatSourceType(item.sourceType)}] ${item.title}`);
      lines.push(`  Evidence ID:          ${item.id}`);
      lines.push(`  Added At:             ${item.addedAt}`);
      lines.push(`  Source Type:          ${item.sourceType}`);

      if (item.payload.sourceType === "text_analysis") {
        const p = item.payload as TextAnalysisPayload;
        lines.push(`  Assessment:           ${p.result.assessment}`);
        lines.push(`  Category:             ${p.result.category}`);
        lines.push(`  Summary:              ${p.result.summary}`);
        lines.push("  Submitted Message Text (Plain Text):");
        lines.push("  --- BEGIN SUBMITTED MESSAGE TEXT ---");
        lines.push(p.submittedText);
        lines.push("  --- END SUBMITTED MESSAGE TEXT ---");
        if (p.result.warning_signs && p.result.warning_signs.length > 0) {
          lines.push("  Warning Signs Found:");
          p.result.warning_signs.forEach((w) => {
            lines.push(`    * ${w.title}: ${w.explanation}`);
            if (w.evidence_quote) {
              lines.push(`      Quote (Plain Text): "${w.evidence_quote}"`);
            }
          });
        }
        if (p.result.uncertainties && p.result.uncertainties.length > 0) {
          lines.push("  Uncertainties:");
          p.result.uncertainties.forEach((u) => lines.push(`    * ${u}`));
        }
        lines.push(`  Analysis Basis:       ${p.result.analysis_basis || "Submitted text only"}`);
        lines.push(`  Limitation:           ${p.result.limitation || "Evaluates submitted text only."}`);
      } else if (item.payload.sourceType === "extracted_text") {
        const p = item.payload as ExtractedTextPayload;
        lines.push(
          `  Extraction Type:      ${
            p.extractionType === "screenshot"
              ? "Screenshot OCR (Tesseract.js)"
              : "PDF Document Extraction (pdfjs-dist)"
          }`
        );
        if (p.fileName) {
          lines.push(`  File Name:            ${p.fileName}`);
        }
        lines.push("  Extracted Content (Plain Text):");
        lines.push("  --- BEGIN EXTRACTED TEXT ---");
        lines.push(p.extractedText);
        lines.push("  --- END EXTRACTED TEXT ---");
      } else if (item.payload.sourceType === "url_structure") {
        const p = item.payload as UrlStructurePayload;
        lines.push(`  Submitted URL (Plain Text): ${p.url}`);
        lines.push(`  Hostname:             ${p.result.hostname || "N/A"}`);
        lines.push(`  Scheme:               ${p.result.scheme || "N/A"}`);
        lines.push(`  Path:                 ${p.result.path || "N/A"}`);
        if (p.result.query) {
          lines.push(`  Query:                ${p.result.query}`);
        }
        if (p.result.has_userinfo && p.result.userinfo) {
          lines.push(`  Embedded Userinfo:    ${p.result.userinfo}`);
        }
        lines.push(`  Summary:              ${p.result.summary}`);
        if (p.result.observations && p.result.observations.length > 0) {
          lines.push("  Structural Observations:");
          p.result.observations.forEach((obs) => {
            lines.push(`    * [${obs.level.toUpperCase()}] ${obs.title}: ${obs.description}`);
          });
        }
        lines.push(`  Inspection Basis:     ${p.result.inspection_basis || "URL structure only"}`);
      } else if (item.payload.sourceType === "url_reputation") {
        const p = item.payload as UrlReputationPayload;
        const expired = isReputationExpired(p, nowMs);
        lines.push(`  Checked URL (Plain Text):   ${p.url}`);
        lines.push(`  Reputation Outcome:   ${p.result.status.replace(/_/g, " ").toUpperCase()}`);
        lines.push(`  Provider:             ${p.result.provider || "Google Safe Browsing"}`);
        lines.push(`  Checked Timestamp:    ${p.checked_at}`);
        lines.push(`  Provider Expiry:      ${p.expires_at || "None (30-minute display freshness applies)"}`);
        lines.push(`  Freshness Status:     ${expired ? "HISTORICAL CONTEXT (EXPIRED)" : "Active / Fresh"}`);
        if (p.result.threat_types && p.result.threat_types.length > 0) {
          lines.push(`  Threat Categories:    ${p.result.threat_types.join(", ")}`);
        }
        lines.push(`  Summary:              ${p.result.summary}`);
        // Safe Browsing attribution & no-match disclaimer preservation
        lines.push(`  Attribution:          ${p.result.attribution || "Data provided by Google Safe Browsing."}`);
        lines.push(
          `  Advisory / Disclaimer: ${
            p.result.advisory ||
            "A 'No Known Threat Matches' lookup evaluates threat feed inclusion only and does not guarantee that the destination is safe, benign, or authentic."
          }`
        );
      }
      lines.push("");
    });
  }

  lines.push(dividerDouble);
  lines.push("END OF REPORT - FRAUDLENS");
  lines.push(dividerDouble);

  return lines.join("\n");
}

/**
 * Triggers a client-side UTF-8 .txt download of the case report in the browser.
 * No API requests or storage modifications are performed.
 */
export function downloadCaseReport(currentCase: Case, nowMs: number = Date.now()): void {
  if (!currentCase || !currentCase.evidence || currentCase.evidence.length === 0) {
    return;
  }

  const reportContent = generateCaseReportText(currentCase, nowMs);
  const blob = new Blob([reportContent], { type: "text/plain;charset=utf-8" });
  const objectUrl = URL.createObjectURL(blob);

  const slug =
    currentCase.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "") || "case";

  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `${slug}-report.txt`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  URL.revokeObjectURL(objectUrl);
}
