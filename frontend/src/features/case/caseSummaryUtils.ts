import {
  Case,
  EvidenceItem,
  ExtractedTextPayload,
  TextAnalysisPayload,
  UrlReputationPayload,
  UrlStructurePayload,
} from "../../types/case";
import { UrlInspectionResponse, UrlObservation } from "../../types/api";

export interface SummaryWarningSign {
  id: string;
  title: string;
  sourceType: "text_analysis" | "url_reputation" | "url_structure";
  evidenceId: string;
  evidenceTitle: string;
  detail: string;
  quoteOrUrl?: string;
  isHistorical?: boolean;
}

export interface SummaryConflict {
  id: string;
  title: string;
  description: string;
  evidenceIds: string[];
}

export interface TemporalObservationItem {
  evidenceId: string;
  evidenceTitle: string;
  status: string;
  checkedAt: string;
  isExpired: boolean;
}

export interface SummaryTemporalObservation {
  id: string;
  url: string;
  observations: TemporalObservationItem[];
}

export interface SummaryUnknown {
  id: string;
  title: string;
  description: string;
  evidenceId?: string;
  evidenceTitle?: string;
}

export interface SummaryVerificationStep {
  id: string;
  step: string;
  sourceEvidenceId?: string;
  sourceEvidenceTitle?: string;
}

export interface CaseSummaryResult {
  warningSigns: SummaryWarningSign[];
  conflicts: SummaryConflict[];
  temporalObservations: SummaryTemporalObservation[];
  unknowns: SummaryUnknown[];
  verificationSteps: SummaryVerificationStep[];
  hasEvidence: boolean;
}

export function isReputationExpired(payload: UrlReputationPayload, nowMs: number): boolean {
  if (payload.is_stale) {
    return true;
  }
  if (nowMs <= 0) {
    return payload.is_stale;
  }
  const checkedTime = new Date(payload.checked_at).getTime();
  const expiryTime = payload.expires_at ? new Date(payload.expires_at).getTime() : NaN;
  if (!isNaN(expiryTime) && nowMs >= expiryTime) {
    return true;
  }
  if (nowMs >= checkedTime + 30 * 60 * 1000) {
    return true;
  }
  return false;
}

export function generateCaseSummary(currentCase: Case | null, nowMs: number): CaseSummaryResult {
  if (!currentCase || !currentCase.evidence || currentCase.evidence.length === 0) {
    return {
      warningSigns: [],
      conflicts: [],
      temporalObservations: [],
      unknowns: [],
      verificationSteps: [],
      hasEvidence: false,
    };
  }

  const warningSigns: SummaryWarningSign[] = [];
  const conflicts: SummaryConflict[] = [];
  const temporalObservations: SummaryTemporalObservation[] = [];
  const unknowns: SummaryUnknown[] = [];
  const verificationSteps: SummaryVerificationStep[] = [];

  const evidence = currentCase.evidence;

  // 1. Warning Signs Extraction
  for (const item of evidence) {
    if (item.payload.sourceType === "text_analysis") {
      const payload: TextAnalysisPayload = item.payload;
      const res = payload.result;
      if (res.warning_signs && res.warning_signs.length > 0) {
        res.warning_signs.forEach((sign, idx) => {
          warningSigns.push({
            id: `warning-${item.id}-${idx}`,
            title: sign.title,
            sourceType: "text_analysis",
            evidenceId: item.id,
            evidenceTitle: item.title,
            detail: sign.explanation,
            quoteOrUrl: sign.evidence_quote,
            isHistorical: false,
          });
        });
      }
    } else if (item.payload.sourceType === "url_reputation") {
      const payload: UrlReputationPayload = item.payload;
      const res = payload.result;
      if (res.status === "threat_match") {
        const expired = isReputationExpired(payload, nowMs);
        const categories = res.threat_types.length > 0 ? res.threat_types.join(", ") : "Unspecified Threat";
        if (expired) {
          warningSigns.push({
            id: `warning-rep-${item.id}`,
            title: `Reported Threat Destination (Historical - Expired)`,
            sourceType: "url_reputation",
            evidenceId: item.id,
            evidenceTitle: item.title,
            detail: `Google Safe Browsing previously reported this URL under threat categories: ${categories}. This check has expired and is treated as historical context.`,
            quoteOrUrl: payload.url,
            isHistorical: true,
          });
        } else {
          warningSigns.push({
            id: `warning-rep-${item.id}`,
            title: `Safe Browsing Threat Match (${categories})`,
            sourceType: "url_reputation",
            evidenceId: item.id,
            evidenceTitle: item.title,
            detail: `Google Safe Browsing flagged this destination as an active threat (${categories}).`,
            quoteOrUrl: payload.url,
            isHistorical: false,
          });
        }
      }
    } else if (item.payload.sourceType === "url_structure") {
      const payload: UrlStructurePayload = item.payload;
      const res: UrlInspectionResponse = payload.result;
      if (res.observations && res.observations.length > 0) {
        res.observations
          .filter((obs: UrlObservation) => obs.level === "caution" || obs.level === "warning")
          .forEach((obs: UrlObservation) => {
            warningSigns.push({
              id: `warning-struct-${item.id}-${obs.id}`,
              title: `Structural Flag: ${obs.title}`,
              sourceType: "url_structure",
              evidenceId: item.id,
              evidenceTitle: item.title,
              detail: obs.description,
              quoteOrUrl: payload.url,
              isHistorical: false,
            });
          });
      }
    }
  }

  // 2. Conflicting Findings (Strict Disagreement Invariant)
  // Rule 1: A "No Known Threat Matches" reputation result does NOT contradict a message analysis warning sign.
  // Rule 2: Different assessments of different messages are NOT conflicts. Only show a conflict when two findings make incompatible claims about the SAME subject under comparable conditions.
  const textAnalyses = evidence.filter((e) => e.payload.sourceType === "text_analysis");

  // Group text analyses by exact submitted text to find whether conflicting claims exist for the SAME message
  const textByContent: Record<string, EvidenceItem[]> = {};
  for (const item of textAnalyses) {
    const textPayload = item.payload as TextAnalysisPayload;
    const exactText = textPayload.submittedText;
    if (!textByContent[exactText]) {
      textByContent[exactText] = [];
    }
    textByContent[exactText].push(item);
  }

  for (const [, items] of Object.entries(textByContent)) {
    if (items.length > 1) {
      const warnItem = items.find(
        (i) => (i.payload as TextAnalysisPayload).result.assessment === "warning_signs_found"
      );
      const cleanItem = items.find(
        (i) => (i.payload as TextAnalysisPayload).result.assessment === "no_clear_warning_signs"
      );
      if (warnItem && cleanItem) {
        conflicts.push({
          id: `conflict-text-same-message-${warnItem.id}-${cleanItem.id}`,
          title: "Incompatible Assessments for Identical Message Text",
          description: `Two analyses evaluated the exact same message text under comparable conditions with contradictory conclusions: "${warnItem.title}" found warning signs, whereas "${cleanItem.title}" found no clear warning signs.`,
          evidenceIds: [warnItem.id, cleanItem.id],
        });
      }
    }
  }

  // Rule 3: A Safe Browsing match and a no-match for the same URL do not by themselves establish a conflict.
  // If they were checked at different times, show them as separate observations with timestamps.
  // Expired results are historical context.
  const reputationItems = evidence.filter((e) => e.payload.sourceType === "url_reputation");
  const repByUrl: Record<string, EvidenceItem[]> = {};
  for (const item of reputationItems) {
    if (item.payload.sourceType === "url_reputation") {
      const u = (item.payload as UrlReputationPayload).url.toLowerCase();
      if (!repByUrl[u]) {
        repByUrl[u] = [];
      }
      repByUrl[u].push(item);
    }
  }

  for (const [urlKey, items] of Object.entries(repByUrl)) {
    if (items.length > 1) {
      const timestamps = new Set(
        items.map((i) => (i.payload as UrlReputationPayload).checked_at)
      );

      // If checks occurred at different times, record them as separate observations over time, NOT a conflict
      if (timestamps.size > 1) {
        temporalObservations.push({
          id: `obs-temporal-${urlKey}`,
          url: (items[0]?.payload as UrlReputationPayload).url || urlKey,
          observations: items
            .map((i) => {
              const p = i.payload as UrlReputationPayload;
              return {
                evidenceId: i.id,
                evidenceTitle: i.title,
                status: p.result.status,
                checkedAt: p.checked_at,
                isExpired: isReputationExpired(p, nowMs),
              };
            })
            .sort((a, b) => new Date(a.checkedAt).getTime() - new Date(b.checkedAt).getTime()),
        });
      }
    }
  }

  // 3. What Remains Unknown
  // A. Check for expired reputation findings (treated as historical context, current status unknown)
  for (const item of reputationItems) {
    if (item.payload.sourceType === "url_reputation") {
      const payload = item.payload as UrlReputationPayload;
      if (isReputationExpired(payload, nowMs)) {
        unknowns.push({
          id: `unknown-rep-expired-${item.id}`,
          title: `Current Threat Status Unknown (Expired Lookup)`,
          description: `The reputation finding for destination "${payload.url}" has expired or was captured over 30 minutes ago. It is treated as historical context; current threat status is unknown until a fresh check is performed.`,
          evidenceId: item.id,
          evidenceTitle: item.title,
        });
      }
      if (payload.result.status === "unavailable" || (payload.result.status as string) === "service_unavailable") {
        unknowns.push({
          id: `unknown-rep-unavail-${item.id}`,
          title: `Reputation Feed Unavailable`,
          description: `The Safe Browsing check for destination "${payload.url}" was unavailable on the server host. External threat intelligence could not be obtained.`,
          evidenceId: item.id,
          evidenceTitle: item.title,
        });
      }
    }
  }

  // B. Check for URL structure items that have NO corresponding reputation check
  const structureItems = evidence.filter((e) => e.payload.sourceType === "url_structure");
  for (const item of structureItems) {
    if (item.payload.sourceType === "url_structure") {
      const structPayload = item.payload as UrlStructurePayload;
      const hasRep = reputationItems.some(
        (r) =>
          r.payload.sourceType === "url_reputation" &&
          (r.payload as UrlReputationPayload).url.toLowerCase() === structPayload.url.toLowerCase()
      );
      if (!hasRep) {
        unknowns.push({
          id: `unknown-struct-norep-${item.id}`,
          title: `External Reputation Not Checked for Inspected URL`,
          description: `URL structure was inspected locally for "${structPayload.url}", but external threat intelligence (Safe Browsing) was not checked for this destination.`,
          evidenceId: item.id,
          evidenceTitle: item.title,
        });
      }
    }
  }

  // C. Check if raw extracted text exists without message analysis
  const extractedTextItems = evidence.filter((e) => e.payload.sourceType === "extracted_text");
  if (extractedTextItems.length > 0 && textAnalyses.length === 0) {
    extractedTextItems.forEach((item) => {
      if (item.payload.sourceType === "extracted_text") {
        const payload = item.payload as ExtractedTextPayload;
        unknowns.push({
          id: `unknown-extract-no-analysis-${item.id}`,
          title: `Extracted Text Awaiting Risk Analysis`,
          description: `The case contains text extracted from ${payload.fileName || (payload.extractionType === "screenshot" ? "screenshot" : "document")}, but suspicious message risk analysis has not been performed on it.`,
          evidenceId: item.id,
          evidenceTitle: item.title,
        });
      }
    });
  }

  // D. If case has NO reputation checks at all
  if (reputationItems.length === 0) {
    unknowns.push({
      id: "unknown-no-reputation-checks",
      title: "No External Threat Reputation Checks in Case",
      description: "No destinations in this case have been verified against external threat intelligence feeds (such as Google Safe Browsing).",
    });
  }

  // E. Message Analysis Uncertainties
  for (const item of textAnalyses) {
    if (item.payload.sourceType === "text_analysis") {
      const payload = item.payload as TextAnalysisPayload;
      const res = payload.result;
      if (res.uncertainties && res.uncertainties.length > 0) {
        res.uncertainties.forEach((unc, idx) => {
          unknowns.push({
            id: `unknown-analysis-${item.id}-${idx}`,
            title: `Analysis Uncertainty`,
            description: unc,
            evidenceId: item.id,
            evidenceTitle: item.title,
          });
        });
      }
    }
  }

  // F. Fundamental FraudLens Boundary Unknown
  unknowns.push({
    id: "unknown-sender-identity",
    title: "Sender Identity & Remote Server Legitimacy Unverified",
    description: "FraudLens evaluates submitted textual content and URL syntax only. Remote server existence, DNS records, domain ownership, and physical sender identity remain unverified.",
  });

  // 4. Practical Verification Steps
  // Always include primary trusted-channel step
  verificationSteps.push({
    id: "step-trusted-channel",
    step: "Contact the claimed organization directly through an independent, verified channel you already trust (such as the phone number on the back of your payment card, an official account statement, or their verified website). Never use contact details, phone numbers, or links provided in the message.",
  });

  // Aggregate steps from text analyses
  const seenSteps = new Set<string>();
  seenSteps.add(verificationSteps[0]!.step);

  for (const item of textAnalyses) {
    if (item.payload.sourceType === "text_analysis") {
      const payload = item.payload as TextAnalysisPayload;
      const res = payload.result;
      if (res.verification_steps && res.verification_steps.length > 0) {
        res.verification_steps.forEach((step, idx) => {
          const trimmed = step.trim();
          if (!seenSteps.has(trimmed)) {
            seenSteps.add(trimmed);
            verificationSteps.push({
              id: `step-analysis-${item.id}-${idx}`,
              step: trimmed,
              sourceEvidenceId: item.id,
              sourceEvidenceTitle: item.title,
            });
          }
        });
      }
    }
  }

  // If URLs exist in the case
  if (structureItems.length > 0 || reputationItems.length > 0) {
    const urlStep = "Verify destination domain ownership and registration records independently before entering credentials, personal details, or authentication codes.";
    if (!seenSteps.has(urlStep)) {
      seenSteps.add(urlStep);
      verificationSteps.push({
        id: "step-verify-domain",
        step: urlStep,
      });
    }
  }

  // If warning signs exist in the case
  if (warningSigns.length > 0) {
    const paymentStep = "Never transfer upfront registration fees, refundable deposits, or share SMS one-time passwords (OTPs) to receive a job offer, prize, or loan.";
    if (!seenSteps.has(paymentStep)) {
      seenSteps.add(paymentStep);
      verificationSteps.push({
        id: "step-no-upfront-fees",
        step: paymentStep,
      });
    }
  }

  return {
    warningSigns,
    conflicts,
    temporalObservations,
    unknowns,
    verificationSteps,
    hasEvidence: true,
  };
}
