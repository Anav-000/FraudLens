import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Case } from "../types/case";
import {
  FRAUDLENS_STORAGE_KEY,
  validateSavedCase,
  recalculateCaseFreshness,
  saveCaseToStorage,
  loadCaseFromStorage,
  deleteCaseFromStorage,
} from "../features/case/caseStorage";
import { CaseBuilder } from "../features/case/CaseBuilder";
import * as api from "../lib/api";

const mockTextAnalysisResult = {
  assessment: "warning_signs_found" as const,
  category: "phishing" as const,
  summary: "Phishing lure detected.",
  warning_signs: [{ title: "Urgent Deadline", evidence_quote: "Now", explanation: "Pressures user" }],
  uncertainties: [],
  verification_steps: ["Call bank"],
  language: "en" as const,
  analysis_basis: "submitted_text_only",
  external_checks_performed: false,
  limitation: "Limitation",
};

const mockUrlInspectionResult = {
  submitted_url: "https://secure-bank.example.invalid",
  scheme: "https",
  hostname: "secure-bank.example.invalid",
  hostname_ascii: "secure-bank.example.invalid",
  hostname_unicode: "secure-bank.example.invalid",
  port: null,
  is_default_port: true,
  path: "",
  query: null,
  fragment: null,
  has_userinfo: false,
  userinfo: null,
  is_ip_address: false,
  ip_version: null,
  ip_scope: null,
  is_punycode: false,
  registrable_domain: "example.invalid",
  subdomain_count: 1,
  subdomains: ["secure-bank"],
  observations: [],
  summary: "Valid URL",
  inspection_basis: "url_structure_only",
  external_checks_performed: false,
  notice: "",
  limitation: "",
};

const sampleCase: Case = {
  id: "case-storage-test",
  name: "Phishing SMS Investigation",
  createdAt: "2026-11-13T10:00:00.000Z",
  evidence: [
    {
      id: "ev-1",
      sourceType: "text_analysis",
      title: "Bank Phishing Lure",
      addedAt: "2026-11-13T10:01:00.000Z",
      payload: {
        sourceType: "text_analysis",
        submittedText: "Your account is locked. Verify now.",
        result: mockTextAnalysisResult,
      },
    },
    {
      id: "ev-2",
      sourceType: "url_structure",
      title: "Dest URL",
      addedAt: "2026-11-13T10:02:00.000Z",
      payload: {
        sourceType: "url_structure",
        url: "https://secure-bank.example.invalid",
        result: mockUrlInspectionResult,
      },
    },
  ],
};

describe("caseStorage Unit Functions", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("validates a compliant Case object", () => {
    const validated = validateSavedCase(sampleCase);
    expect(validated).not.toBeNull();
    expect(validated?.name).toBe("Phishing SMS Investigation");
    expect(validated?.evidence).toHaveLength(2);
  });

  it("rejects non-object, missing fields, or invalid schemas", () => {
    expect(validateSavedCase(null)).toBeNull();
    expect(validateSavedCase("string")).toBeNull();
    expect(validateSavedCase({})).toBeNull();
    expect(validateSavedCase({ id: "c1" })).toBeNull(); // missing name, createdAt, evidence
    expect(validateSavedCase({ id: "c1", name: "test", createdAt: "invalid-date", evidence: [] })).toBeNull();
    expect(validateSavedCase({ id: "c1", name: "test", createdAt: new Date().toISOString(), evidence: "not-an-array" })).toBeNull();

    // Invalid evidence item
    const badEvidenceCase = {
      id: "c1",
      name: "test",
      createdAt: new Date().toISOString(),
      evidence: [{ id: "e1", sourceType: "unrecognized_type", title: "bad", addedAt: new Date().toISOString(), payload: {} }],
    };
    expect(validateSavedCase(badEvidenceCase)).toBeNull();
  });

  it("recalculates reputation freshness when reopening a case", () => {
    const pastCheckTime = new Date(Date.now() - 3600000).toISOString(); // 1 hour ago
    const expiredLookupCase: Case = {
      id: "case-expired-rep",
      name: "Expired Reputation Case",
      createdAt: pastCheckTime,
      evidence: [
        {
          id: "ev-rep",
          sourceType: "url_reputation",
          title: "Safe Browsing Check",
          addedAt: pastCheckTime,
          payload: {
            sourceType: "url_reputation",
            url: "https://example.invalid",
            checked_at: pastCheckTime,
            expires_at: new Date(Date.now() - 1800000).toISOString(),
            is_stale: false, // was fresh when checked 1 hour ago
            result: {
              status: "no_known_match",
              provider: "Google Safe Browsing (v4)",
              threat_types: [],
              checked_url: "https://example.invalid",
              checked_at: pastCheckTime,
              expires_at: new Date(Date.now() - 1800000).toISOString(),
              is_cached: false,
              is_stale: false,
              summary: "Clean",
              advisory: "Advisory",
              attribution: "Google Safe Browsing",
            },
          },
        },
      ],
    };

    const recalculated = recalculateCaseFreshness(expiredLookupCase, Date.now());
    const repPayload = recalculated.evidence[0]?.payload;
    if (repPayload && repPayload.sourceType === "url_reputation") {
      expect(repPayload.is_stale).toBe(true);
      expect(repPayload.result.is_stale).toBe(true);
    } else {
      throw new Error("Expected url_reputation payload");
    }
  });

  it("saves, loads, and deletes case from storage cleanly", () => {
    const saveRes = saveCaseToStorage(sampleCase);
    expect(saveRes.success).toBe(true);
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).not.toBeNull();

    const loadRes = loadCaseFromStorage();
    expect(loadRes.case).not.toBeNull();
    expect(loadRes.case?.name).toBe("Phishing SMS Investigation");

    const deleteRes = deleteCaseFromStorage();
    expect(deleteRes.success).toBe(true);
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).toBeNull();
  });

  it("gracefully returns an error message when stored JSON is corrupted", () => {
    localStorage.setItem(FRAUDLENS_STORAGE_KEY, "{ corrupted json !");
    const loadRes = loadCaseFromStorage();
    expect(loadRes.case).toBeNull();
    expect(loadRes.error).toContain("corrupted");
  });

  it("handles storage write exceptions (quota exceeded)", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError: quota was exceeded");
    });

    try {
      const res = saveCaseToStorage(sampleCase);
      expect(res.success).toBe(false);
      expect(res.error).toContain("quota was exceeded");
    } finally {
      setItemSpy.mockRestore();
    }
  });
});

describe("CaseBuilder Local Saving and Reopening UI", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("keeps new cases in memory by default and does not write to localStorage until user opts in", () => {
    render(
      <CaseBuilder
        currentCase={sampleCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    // Initial state: nothing in localStorage
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("save-case-device-btn")).toBeInTheDocument();
  });

  it("displays sensitivity and persistence disclosure before saving to device", async () => {
    const user = userEvent.setup();
    render(
      <CaseBuilder
        currentCase={sampleCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    // Click "Save on This Device"
    await user.click(screen.getByTestId("save-case-device-btn"));

    // Confirmation dialog must appear
    const dialog = screen.getByTestId("save-case-confirm-dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByText(/This case and its evidence may contain sensitive personal or financial information/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/will remain accessible after refreshing the page/i)
    ).toBeInTheDocument();

    // Cancel closes dialog without writing
    await user.click(screen.getByTestId("cancel-save-case-btn"));
    expect(screen.queryByTestId("save-case-confirm-dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).toBeNull();

    // Click again and confirm save
    await user.click(screen.getByTestId("save-case-device-btn"));
    await user.click(screen.getByTestId("confirm-save-case-btn"));

    // Success banner appears and localStorage holds data
    expect(screen.getByTestId("case-storage-status-banner")).toBeInTheDocument();
    expect(screen.getByText(/Case saved on this device/i)).toBeInTheDocument();
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).not.toBeNull();
  });

  it("allows reopening saved case after refresh and re-evaluates freshness", async () => {
    const user = userEvent.setup();
    const handleReopen = vi.fn();

    // Pre-populate storage with a saved case (simulating a prior save before refresh)
    saveCaseToStorage(sampleCase);

    render(
      <CaseBuilder
        currentCase={null} // no active case, simulating page reload
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
        onReopenCase={handleReopen}
      />
    );

    // Card indicating saved case on device must appear
    expect(screen.getByTestId("saved-case-restore-card")).toBeInTheDocument();
    expect(screen.getByText(/Phishing SMS Investigation/i)).toBeInTheDocument();

    const reopenBtn = screen.getByTestId("reopen-saved-case-btn");
    await user.click(reopenBtn);

    expect(handleReopen).toHaveBeenCalledTimes(1);
    expect(handleReopen.mock.calls[0]![0].name).toBe("Phishing SMS Investigation");
  });

  it("warns before replacing an existing saved case when saving another case", async () => {
    const user = userEvent.setup();
    // Storage already contains a previously saved case
    saveCaseToStorage(sampleCase);

    const newCase: Case = {
      id: "case-new",
      name: "Different Job Scam Case",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    render(
      <CaseBuilder
        currentCase={newCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    await user.click(screen.getByTestId("save-case-device-btn"));

    // Confirmation dialog must specifically warn about replacing the existing saved case
    expect(
      screen.getByText(/A case \(“Phishing SMS Investigation”\) is already saved on this device. Saving will replace it./i)
    ).toBeInTheDocument();

    // Confirm overwrite
    await user.click(screen.getByTestId("confirm-save-case-btn"));
    const stored = JSON.parse(localStorage.getItem(FRAUDLENS_STORAGE_KEY)!);
    expect(stored.name).toBe("Different Job Scam Case");
  });

  it("asks before discarding unsaved work when reopening a saved case over an active case", async () => {
    const user = userEvent.setup();
    const handleReopen = vi.fn();
    saveCaseToStorage(sampleCase);

    const activeUnsavedCase: Case = {
      id: "case-unsaved",
      name: "Unsaved Work Case",
      createdAt: new Date().toISOString(),
      evidence: [
        {
          id: "ev-u1",
          sourceType: "text_analysis",
          title: "Unsaved Item",
          addedAt: new Date().toISOString(),
          payload: {
            sourceType: "text_analysis",
            submittedText: "Unsaved text",
            result: mockTextAnalysisResult,
          },
        },
      ],
    };

    render(
      <CaseBuilder
        currentCase={activeUnsavedCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
        onReopenCase={handleReopen}
      />
    );

    // Reopen button is clicked while active case has unsaved evidence
    await user.click(screen.getByTestId("reopen-saved-case-btn"));

    // Must show reopen confirmation dialog
    const dialog = screen.getByTestId("reopen-case-confirm-dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByText(/Any unsaved evidence in the active case will be discarded/i)
    ).toBeInTheDocument();

    // Cancel preserves active case and does not load
    await user.click(screen.getByTestId("cancel-reopen-case-btn"));
    expect(handleReopen).not.toHaveBeenCalled();

    // Click again and confirm discard & reopen
    await user.click(screen.getByTestId("reopen-saved-case-btn"));
    await user.click(screen.getByTestId("confirm-reopen-case-btn"));

    expect(handleReopen).toHaveBeenCalledWith(expect.objectContaining({ name: "Phishing SMS Investigation" }));
  });

  it("deletes saved case while clarifying that open active in-memory case remains open", async () => {
    const user = userEvent.setup();
    saveCaseToStorage(sampleCase);

    render(
      <CaseBuilder
        currentCase={sampleCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    // Click Delete Saved Case
    await user.click(screen.getByTestId("delete-saved-case-btn"));

    // Confirmation dialog must clarify that in-memory case will remain open
    const dialog = screen.getByTestId("delete-saved-case-confirm-dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByText(/Your open in-memory case will remain open until you delete it or refresh the page/i)
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("confirm-delete-saved-btn"));

    // Storage is cleared
    expect(localStorage.getItem(FRAUDLENS_STORAGE_KEY)).toBeNull();
    // Success status informs user that in-memory case is untouched
    expect(
      screen.getByText(/The saved copy was deleted from this device. Your active in-memory case remains open/i)
    ).toBeInTheDocument();
  });

  it("shows a clear message and preserves the active case when stored data is invalid", async () => {
    const user = userEvent.setup();
    const handleReopen = vi.fn();

    // Place invalid data in localStorage
    localStorage.setItem(FRAUDLENS_STORAGE_KEY, JSON.stringify({ invalid: "data", notACase: true }));

    render(
      <CaseBuilder
        currentCase={sampleCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
        onReopenCase={handleReopen}
      />
    );

    // Try to reopen
    await user.click(screen.getByTestId("reopen-saved-case-btn"));
    await user.click(screen.getByTestId("confirm-reopen-case-btn"));

    // Error banner appears
    expect(screen.getByTestId("case-storage-error-banner")).toBeInTheDocument();
    expect(
      screen.getByText(/The stored case data on this device is invalid or does not match the case schema/i)
    ).toBeInTheDocument();

    // onReopenCase must NOT be called, preserving the active case
    expect(handleReopen).not.toHaveBeenCalled();
    expect(screen.getByTestId("active-case-name")).toHaveTextContent("Phishing SMS Investigation");
  });

  it("performs saving, reopening, and deleting without making any API requests", async () => {
    const user = userEvent.setup();
    const analyzeSpy = vi.spyOn(api, "analyzeText");
    const checkSpy = vi.spyOn(api, "checkBackendConnection");

    render(
      <CaseBuilder
        currentCase={sampleCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
        onReopenCase={vi.fn()}
      />
    );

    // Save
    await user.click(screen.getByTestId("save-case-device-btn"));
    await user.click(screen.getByTestId("confirm-save-case-btn"));

    // Delete
    await user.click(screen.getByTestId("delete-saved-case-btn"));
    await user.click(screen.getByTestId("confirm-delete-saved-btn"));

    // Zero API calls
    expect(analyzeSpy).not.toHaveBeenCalled();
    expect(checkSpy).not.toHaveBeenCalled();
  });
});
