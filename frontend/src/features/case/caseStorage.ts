import { Case, EvidenceItem, UrlReputationPayload } from "../../types/case";
import { isReputationExpired } from "./caseSummaryUtils";

export const FRAUDLENS_STORAGE_KEY = "fraudlens_saved_case";

export interface SavedCaseMeta {
  exists: boolean;
  id?: string;
  name?: string;
  createdAt?: string;
  evidenceCount?: number;
}

/**
 * Validates untrusted data from browser storage to ensure it conforms strictly
 * to the Case schema and contains no malformed evidence payloads.
 */
export function validateSavedCase(raw: unknown): Case | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const obj = raw as Record<string, unknown>;

  if (typeof obj.id !== "string" || !obj.id.trim()) {
    return null;
  }
  if (typeof obj.name !== "string" || !obj.name.trim()) {
    return null;
  }
  if (typeof obj.createdAt !== "string" || isNaN(Date.parse(obj.createdAt))) {
    return null;
  }
  if (!Array.isArray(obj.evidence)) {
    return null;
  }

  const validatedEvidence: EvidenceItem[] = [];

  for (const item of obj.evidence) {
    if (!item || typeof item !== "object") {
      return null;
    }
    const ev = item as Record<string, unknown>;

    if (typeof ev.id !== "string" || !ev.id.trim()) {
      return null;
    }
    if (typeof ev.title !== "string") {
      return null;
    }
    if (typeof ev.addedAt !== "string" || isNaN(Date.parse(ev.addedAt))) {
      return null;
    }

    if (
      ev.sourceType !== "text_analysis" &&
      ev.sourceType !== "extracted_text" &&
      ev.sourceType !== "url_structure" &&
      ev.sourceType !== "url_reputation"
    ) {
      return null;
    }

    if (!ev.payload || typeof ev.payload !== "object") {
      return null;
    }
    const p = ev.payload as Record<string, unknown>;
    if (p.sourceType !== ev.sourceType) {
      return null;
    }

    if (p.sourceType === "text_analysis") {
      if (typeof p.submittedText !== "string") return null;
      if (!p.result || typeof p.result !== "object") return null;
      const res = p.result as Record<string, unknown>;
      if (typeof res.assessment !== "string") return null;
      if (typeof res.summary !== "string") return null;
      validatedEvidence.push(ev as unknown as EvidenceItem);
    } else if (p.sourceType === "extracted_text") {
      if (p.extractionType !== "screenshot" && p.extractionType !== "document") return null;
      if (typeof p.extractedText !== "string") return null;
      validatedEvidence.push(ev as unknown as EvidenceItem);
    } else if (p.sourceType === "url_structure") {
      if (typeof p.url !== "string") return null;
      if (!p.result || typeof p.result !== "object") return null;
      validatedEvidence.push(ev as unknown as EvidenceItem);
    } else if (p.sourceType === "url_reputation") {
      if (typeof p.url !== "string") return null;
      if (!p.result || typeof p.result !== "object") return null;
      if (typeof p.checked_at !== "string" || isNaN(Date.parse(p.checked_at))) return null;
      if (typeof p.is_stale !== "boolean") return null;
      validatedEvidence.push(ev as unknown as EvidenceItem);
    } else {
      return null;
    }
  }

  return {
    id: obj.id,
    name: obj.name,
    createdAt: obj.createdAt,
    evidence: validatedEvidence,
  };
}

/**
 * Re-evaluates reputation freshness against the current timestamp (or given nowMs)
 * whenever a saved case is loaded or reopened from storage.
 */
export function recalculateCaseFreshness(savedCase: Case, nowMs: number = Date.now()): Case {
  const updatedEvidence = savedCase.evidence.map((item) => {
    if (item.sourceType === "url_reputation" && item.payload.sourceType === "url_reputation") {
      const p = item.payload as UrlReputationPayload;
      const expired = isReputationExpired(p, nowMs);
      return {
        ...item,
        payload: {
          ...p,
          is_stale: expired,
          result: {
            ...p.result,
            is_stale: expired,
          },
        },
      };
    }
    return item;
  });

  return {
    ...savedCase,
    evidence: updatedEvidence,
  };
}

/**
 * Checks metadata of the saved case in browser storage without fully loading it.
 */
export function getSavedCaseMeta(): SavedCaseMeta {
  try {
    const raw = localStorage.getItem(FRAUDLENS_STORAGE_KEY);
    if (!raw) {
      return { exists: false };
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      return {
        exists: true,
        id: typeof parsed.id === "string" ? parsed.id : undefined,
        name: typeof parsed.name === "string" ? parsed.name : "Saved Case",
        createdAt: typeof parsed.createdAt === "string" ? parsed.createdAt : undefined,
        evidenceCount: Array.isArray(parsed.evidence) ? parsed.evidence.length : 0,
      };
    }
    return { exists: true, name: "Saved Case" };
  } catch {
    return { exists: false };
  }
}

/**
 * Saves the active case to browser localStorage.
 * No external API requests are performed.
 */
export function saveCaseToStorage(currentCase: Case): { success: boolean; error?: string } {
  try {
    const serialized = JSON.stringify(currentCase);
    localStorage.setItem(FRAUDLENS_STORAGE_KEY, serialized);
    return { success: true };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Access denied or quota exceeded.";
    return {
      success: false,
      error: `Storage is unavailable or quota was exceeded on this device: ${message}`,
    };
  }
}

/**
 * Loads, validates, and recalculates freshness for the saved case from browser localStorage.
 * If data is corrupted or invalid, returns a clear error message and null case.
 */
export function loadCaseFromStorage(nowMs: number = Date.now()): {
  case: Case | null;
  error?: string;
} {
  let rawItem: string | null;
  try {
    rawItem = localStorage.getItem(FRAUDLENS_STORAGE_KEY);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Access denied or storage disabled.";
    return {
      case: null,
      error: `Storage is unavailable: ${message}`,
    };
  }

  if (!rawItem) {
    return { case: null };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawItem);
  } catch {
    return {
      case: null,
      error: "The stored case data on this device is corrupted and cannot be read.",
    };
  }

  const validated = validateSavedCase(parsed);
  if (!validated) {
    return {
      case: null,
      error: "The stored case data on this device is invalid or does not match the case schema.",
    };
  }

  const freshCase = recalculateCaseFreshness(validated, nowMs);
  return { case: freshCase };
}

/**
 * Deletes the stored case copy from browser localStorage.
 */
export function deleteCaseFromStorage(): { success: boolean; error?: string } {
  try {
    localStorage.removeItem(FRAUDLENS_STORAGE_KEY);
    return { success: true };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Access denied.";
    return {
      success: false,
      error: `Unable to delete stored case from this device: ${message}`,
    };
  }
}
