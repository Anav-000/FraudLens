import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Case, EvidenceItem } from "../types/case";
import { TextAnalysisResponse, UrlInspectionResponse, UrlReputationResponse } from "../types/api";
import { generateCaseReportText, downloadCaseReport } from "../features/case/caseReportUtils";
import { CaseBuilder } from "../features/case/CaseBuilder";

const mockTextAnalysis: TextAnalysisResponse = {
  assessment: "warning_signs_found",
  category: "phishing",
  summary: "Urgent bank account suspension lure demanding credentials.",
  warning_signs: [
    {
      title: "False Urgency",
      evidence_quote: "Immediate action required within 24 hours.",
      explanation: "Pressures the user with arbitrary deadlines.",
    },
  ],
  uncertainties: ["SMS sender shortcode unauthenticated."],
  verification_steps: ["Call the bank using the phone number on the back of your card."],
  language: "en",
  analysis_basis: "submitted_text_only",
  external_checks_performed: false,
  limitation: "Evaluates submitted text only.",
};

const mockUrlInspection: UrlInspectionResponse = {
  submitted_url: "https://mybank.com@secure-verify.example.invalid/login",
  scheme: "https",
  hostname: "secure-verify.example.invalid",
  hostname_ascii: "secure-verify.example.invalid",
  hostname_unicode: "secure-verify.example.invalid",
  port: null,
  is_default_port: true,
  path: "/login",
  query: null,
  fragment: null,
  has_userinfo: true,
  userinfo: "mybank.com",
  is_ip_address: false,
  ip_version: null,
  ip_scope: null,
  is_punycode: false,
  registrable_domain: "example.invalid",
  subdomain_count: 1,
  subdomains: ["secure-verify"],
  observations: [
    {
      id: "userinfo_present",
      title: "Embedded Userinfo Credentials",
      level: "caution",
      description: "Netloc contains credentials before @ symbol.",
    },
  ],
  summary: "URL netloc has embedded userinfo credentials.",
  inspection_basis: "url_structure_only",
  external_checks_performed: false,
  notice: "Notice",
  limitation: "Limitation",
};

const mockReputationFreshThreat: UrlReputationResponse = {
  status: "threat_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: ["SOCIAL_ENGINEERING", "MALWARE"],
  checked_url: "https://phish.example.invalid/dest",
  checked_at: new Date(Date.now() - 60000).toISOString(),
  expires_at: new Date(Date.now() + 600000).toISOString(),
  is_cached: false,
  is_stale: false,
  summary: "Google Safe Browsing threat match detected.",
  advisory: "Threat match advisory.",
  attribution: "Data provided by Google Safe Browsing.",
};

const mockReputationExpiredClean: UrlReputationResponse = {
  status: "no_known_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: [],
  checked_url: "https://clean-site.example.invalid",
  checked_at: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
  expires_at: new Date(Date.now() - 1800000).toISOString(), // expired
  is_cached: false,
  is_stale: true,
  summary: "Historical no known threat match.",
  advisory:
    "A 'No Known Threat Matches' lookup evaluates threat feed inclusion only and does not guarantee that the destination is safe, benign, or authentic.",
  attribution: "Data provided by Google Safe Browsing.",
};

describe("generateCaseReportText", () => {
  const fixedNow = 1794500000000; // deterministic fixed timestamp

  it("includes case name, export time, warning signs, conflicting findings, unknowns, verification steps, and numbered evidence references", () => {
    const item1: EvidenceItem = {
      id: "ev-text-1",
      sourceType: "text_analysis",
      title: "Bank Phishing Lure",
      addedAt: new Date(fixedNow - 300000).toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Your account is locked. Immediate action required within 24 hours.",
        result: mockTextAnalysis,
      },
    };

    const item2: EvidenceItem = {
      id: "ev-struct-2",
      sourceType: "url_structure",
      title: "Userinfo Structural Check",
      addedAt: new Date(fixedNow - 200000).toISOString(),
      payload: {
        sourceType: "url_structure",
        url: "https://mybank.com@secure-verify.example.invalid/login",
        result: mockUrlInspection,
      },
    };

    const activeCase: Case = {
      id: "case-full-report",
      name: "Suspicious Bank Phishing SMS",
      createdAt: new Date(fixedNow - 600000).toISOString(),
      evidence: [item1, item2],
    };

    const report = generateCaseReportText(activeCase, fixedNow);

    // 1. Header & Case Metadata
    expect(report).toContain("FRAUDLENS CASE INVESTIGATION REPORT");
    expect(report).toContain("Case Name:      Suspicious Bank Phishing SMS");
    expect(report).toContain(`Exported At:    ${new Date(fixedNow).toISOString()}`);
    expect(report).toContain("Evidence Items: 2");
    expect(report).toContain("CONFIDENTIALITY & SENSITIVITY NOTICE:");

    // 2. Warning Signs
    expect(report).toContain("1. WARNING SIGNS");
    expect(report).toContain("False Urgency");
    expect(report).toContain("Evidence Reference:   Evidence #1: Bank Phishing Lure");
    expect(report).toContain("Structural Flag: Embedded Userinfo Credentials");
    expect(report).toContain("Evidence Reference:   Evidence #2: Userinfo Structural Check");

    // 3. Conflicting Findings
    expect(report).toContain("2. CONFLICTING FINDINGS");
    expect(report).toContain("No direct conflicts identified in the saved evidence.");

    // 4. What Remains Unknown
    expect(report).toContain("3. WHAT REMAINS UNKNOWN");
    expect(report).toContain("External Reputation Not Checked for Inspected URL");
    expect(report).toContain("Sender Identity & Remote Server Legitimacy Unverified");

    // 5. Practical Verification Steps
    expect(report).toContain("4. PRACTICAL VERIFICATION STEPS");
    expect(report).toContain(
      "Contact the claimed organization directly through an independent, verified channel you already trust"
    );
    expect(report).toContain(
      "Call the bank using the phone number on the back of your card."
    );

    // 6. Numbered Evidence References
    expect(report).toContain("5. NUMBERED EVIDENCE REFERENCES");
    expect(report).toContain("Evidence #1: [Suspicious Message Analysis] Bank Phishing Lure");
    expect(report).toContain("Evidence ID:          ev-text-1");
    expect(report).toContain("Submitted Message Text (Plain Text):");
    expect(report).toContain("Your account is locked. Immediate action required within 24 hours.");

    expect(report).toContain("Evidence #2: [URL Structure Inspection] Userinfo Structural Check");
    expect(report).toContain("Evidence ID:          ev-struct-2");
    expect(report).toContain(
      "Submitted URL (Plain Text): https://mybank.com@secure-verify.example.invalid/login"
    );
    expect(report).toContain("Embedded Userinfo:    mybank.com");

    // End of report
    expect(report).toContain("END OF REPORT - FRAUDLENS");
  });

  it("marks expired reputation results as historical context and preserves Safe Browsing attribution and no-match disclaimer", () => {
    const itemExpiredRep: EvidenceItem = {
      id: "ev-rep-expired",
      sourceType: "url_reputation",
      title: "Old Safe Browsing Check",
      addedAt: new Date(fixedNow - 3600000).toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://clean-site.example.invalid",
        result: mockReputationExpiredClean,
        checked_at: mockReputationExpiredClean.checked_at,
        expires_at: mockReputationExpiredClean.expires_at ?? null,
        is_stale: true,
      },
    };

    const testCase: Case = {
      id: "case-rep-test",
      name: "Reputation Check Case",
      createdAt: new Date(fixedNow - 3600000).toISOString(),
      evidence: [itemExpiredRep],
    };

    const report = generateCaseReportText(testCase, fixedNow);

    // 1. Evidence item marks expired status
    expect(report).toContain("Evidence #1: [URL Threat Reputation (Google Safe Browsing)] Old Safe Browsing Check");
    expect(report).toContain("Freshness Status:     HISTORICAL CONTEXT (EXPIRED)");

    // 2. Safe Browsing attribution preserved
    expect(report).toContain("Attribution:          Data provided by Google Safe Browsing.");

    // 3. No-match disclaimer preserved
    expect(report).toContain("Advisory / Disclaimer:");
    expect(report).toContain(
      "A 'No Known Threat Matches' lookup evaluates threat feed inclusion only and does not guarantee that the destination is safe, benign, or authentic."
    );

    // 4. In Unknowns: Notes current threat status unknown because lookup expired
    expect(report).toContain("Current Threat Status Unknown (Expired Lookup)");
  });

  it("includes active threat match with threat categories and attribution when fresh", () => {
    const itemFreshRep: EvidenceItem = {
      id: "ev-rep-fresh",
      sourceType: "url_reputation",
      title: "Active Threat Destination",
      addedAt: new Date(fixedNow - 60000).toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://phish.example.invalid/dest",
        result: mockReputationFreshThreat,
        checked_at: mockReputationFreshThreat.checked_at,
        expires_at: mockReputationFreshThreat.expires_at ?? null,
        is_stale: false,
      },
    };

    const testCase: Case = {
      id: "case-rep-fresh",
      name: "Fresh Threat Case",
      createdAt: new Date(fixedNow - 60000).toISOString(),
      evidence: [itemFreshRep],
    };

    const report = generateCaseReportText(testCase, fixedNow);

    expect(report).toContain("Freshness Status:     Active / Fresh");
    expect(report).toContain("Threat Categories:    SOCIAL_ENGINEERING, MALWARE");
    expect(report).toContain("Reputation Outcome:   THREAT MATCH");
  });

  it("renders submitted URLs strictly as plain text", () => {
    const rawUrl = "https://example.invalid/path?query=1&auth=token#frag";
    const itemUrl: EvidenceItem = {
      id: "ev-url",
      sourceType: "url_structure",
      title: "URL Test",
      addedAt: new Date(fixedNow).toISOString(),
      payload: {
        sourceType: "url_structure",
        url: rawUrl,
        result: {
          ...mockUrlInspection,
          submitted_url: rawUrl,
        },
      },
    };

    const testCase: Case = {
      id: "case-url",
      name: "URL Plain Text Case",
      createdAt: new Date(fixedNow).toISOString(),
      evidence: [itemUrl],
    };

    const report = generateCaseReportText(testCase, fixedNow);

    // Plain text check
    expect(report).toContain(`Submitted URL (Plain Text): ${rawUrl}`);

    // Must NOT contain HTML anchor tag or markdown link syntax
    expect(report).not.toContain(`<a href=`);
    expect(report).not.toContain(`](${rawUrl})`);
  });

  it("handles empty cases cleanly", () => {
    const emptyCase: Case = {
      id: "case-empty",
      name: "Empty Case",
      createdAt: new Date(fixedNow).toISOString(),
      evidence: [],
    };

    const report = generateCaseReportText(emptyCase, fixedNow);

    expect(report).toContain("Case Name:      Empty Case");
    expect(report).toContain("Evidence Items: 0");
    expect(report).toContain("No warning signs identified in current evidence.");
    expect(report).toContain("No evidence items in case.");
  });
});

describe("downloadCaseReport Function", () => {
  beforeEach(() => {
    vi.spyOn(document.body, "appendChild");
    vi.spyOn(document.body, "removeChild");
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not trigger download when case has no evidence", () => {
    const emptyCase: Case = {
      id: "empty-case",
      name: "No Evidence Case",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    downloadCaseReport(emptyCase);

    expect(document.body.appendChild).not.toHaveBeenCalled();
  });

  it("creates Blob object URL, triggers download anchor, and revokes URL when evidence exists", () => {
    const testCase: Case = {
      id: "valid-case",
      name: "Suspicious Job Offer",
      createdAt: new Date().toISOString(),
      evidence: [
        {
          id: "ev-1",
          sourceType: "text_analysis",
          title: "Telegram Job Offer",
          addedAt: new Date().toISOString(),
          payload: {
            sourceType: "text_analysis",
            submittedText: "Join our team today.",
            result: mockTextAnalysis,
          },
        },
      ],
    };

    downloadCaseReport(testCase);

    // An anchor element should have been appended to document.body and clicked
    expect(document.body.appendChild).toHaveBeenCalled();
    expect(document.body.removeChild).toHaveBeenCalled();
  });
});

describe("CaseBuilder Download UI Component", () => {
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("disables 'Download Case Report' button when the case has no evidence", () => {
    const emptyCase: Case = {
      id: "c-empty",
      name: "Empty Active Case",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    render(
      <CaseBuilder
        currentCase={emptyCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    const downloadBtn = screen.getByTestId("download-case-report-btn");
    expect(downloadBtn).toBeInTheDocument();
    expect(downloadBtn).toBeDisabled();
  });

  it("enables 'Download Case Report' button when evidence is present and displays sensitivity notice", async () => {
    const user = userEvent.setup();
    const caseWithEvidence: Case = {
      id: "c-with-ev",
      name: "Telegram Scam",
      createdAt: new Date().toISOString(),
      evidence: [
        {
          id: "ev-1",
          sourceType: "text_analysis",
          title: "Urgent Payment Lure",
          addedAt: new Date().toISOString(),
          payload: {
            sourceType: "text_analysis",
            submittedText: "Send payment now.",
            result: mockTextAnalysis,
          },
        },
      ],
    };

    render(
      <CaseBuilder
        currentCase={caseWithEvidence}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    // 1. Download button must be enabled
    const downloadBtn = screen.getByTestId("download-case-report-btn");
    expect(downloadBtn).toBeInTheDocument();
    expect(downloadBtn).toBeEnabled();

    // 2. Sensitive Information Notice must be displayed
    const notice = screen.getByTestId("case-report-sensitivity-notice");
    expect(notice).toBeInTheDocument();
    expect(
      screen.getByText(/The downloaded case report includes your saved evidence items in plain text, which may contain sensitive personal or financial information/i)
    ).toBeInTheDocument();

    // 3. Clicking button triggers download logic without throwing
    await user.click(downloadBtn);
  });
});
