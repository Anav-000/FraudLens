import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CaseSummaryPanel } from "../features/case/CaseSummaryPanel";
import { Case, EvidenceItem } from "../types/case";
import { TextAnalysisResponse, UrlInspectionResponse, UrlReputationResponse } from "../types/api";
import { generateCaseSummary } from "../features/case/caseSummaryUtils";

const mockAnalysisWithWarnings: TextAnalysisResponse = {
  assessment: "warning_signs_found",
  category: "phishing",
  summary: "Urgent account suspension lure demanding credentials.",
  warning_signs: [
    {
      title: "False Urgency & Threat",
      evidence_quote: "Your account is suspended. Verify at https://secure-bank.example.invalid now.",
      explanation: "Threatens immediate suspension to pressure the user.",
    },
  ],
  uncertainties: ["SMS sender shortcode could not be authenticated."],
  verification_steps: ["Call the bank using the phone number on your physical card."],
  language: "en",
  analysis_basis: "submitted_text_only",
  external_checks_performed: false,
  limitation: "Evaluates submitted text only.",
};

const mockAnalysisClean: TextAnalysisResponse = {
  assessment: "no_clear_warning_signs",
  category: "other",
  summary: "Routine appointment reminder.",
  warning_signs: [],
  uncertainties: [],
  verification_steps: ["Confirm appointments directly through standard scheduling channels."],
  language: "en",
  analysis_basis: "submitted_text_only",
  external_checks_performed: false,
  limitation: "Evaluates submitted text only.",
};

const mockUrlInspection: UrlInspectionResponse = {
  submitted_url: "https://mybank.com@malicious.example.invalid/login",
  scheme: "https",
  hostname: "malicious.example.invalid",
  hostname_ascii: "malicious.example.invalid",
  hostname_unicode: "malicious.example.invalid",
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
  subdomain_count: 0,
  subdomains: [],
  observations: [
    {
      id: "userinfo_present",
      title: "Embedded Userinfo Credentials",
      level: "caution",
      description: "Netloc contains credentials before @ symbol.",
    },
  ],
  summary: "URL contains userinfo credentials.",
  inspection_basis: "url_structure_only",
  external_checks_performed: false,
  notice: "Notice",
  limitation: "Limitation",
};

const mockReputationThreatFresh: UrlReputationResponse = {
  status: "threat_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: ["SOCIAL_ENGINEERING", "MALWARE"],
  checked_url: "https://phish.example.invalid",
  checked_at: new Date(Date.now() - 60000).toISOString(),
  expires_at: new Date(Date.now() + 600000).toISOString(),
  is_cached: false,
  is_stale: false,
  summary: "Safe Browsing threat match detected.",
  advisory: "High risk destination.",
  attribution: "Data provided by Google Safe Browsing.",
};

const mockReputationThreatExpired: UrlReputationResponse = {
  status: "threat_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: ["SOCIAL_ENGINEERING"],
  checked_url: "https://old-threat.example.invalid",
  checked_at: new Date(Date.now() - 3600000).toISOString(),
  expires_at: new Date(Date.now() - 1800000).toISOString(), // expired
  is_cached: false,
  is_stale: true,
  summary: "Historical Safe Browsing match.",
  advisory: "Threat destination.",
  attribution: "Data provided by Google Safe Browsing.",
};

const mockReputationClean: UrlReputationResponse = {
  status: "no_known_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: [],
  checked_url: "https://clean-site.example.invalid",
  checked_at: new Date(Date.now() - 120000).toISOString(),
  expires_at: new Date(Date.now() + 600000).toISOString(),
  is_cached: false,
  is_stale: false,
  summary: "No known threat match.",
  advisory: "No known match does not guarantee safety.",
  attribution: "Data provided by Google Safe Browsing.",
};

describe("CaseSummaryPanel Component", () => {
  it("renders empty state when case has no evidence", () => {
    const emptyCase: Case = {
      id: "case-empty",
      name: "Empty Case",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    render(<CaseSummaryPanel currentCase={emptyCase} />);

    expect(screen.getByTestId("case-summary-empty")).toBeInTheDocument();
    expect(screen.getByText(/No evidence in case/i)).toBeInTheDocument();
  });

  it("links warning signs to their evidence card via accessible anchor", async () => {
    const user = userEvent.setup();
    const item1: EvidenceItem = {
      id: "ev-text-1",
      sourceType: "text_analysis",
      title: "Bank Phishing SMS",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Your account is suspended. Verify at https://secure-bank.example.invalid now.",
        result: mockAnalysisWithWarnings,
      },
    };

    const caseWithEvidence: Case = {
      id: "case-1",
      name: "Phishing Case",
      createdAt: new Date().toISOString(),
      evidence: [item1],
    };

    // Render with a mock target element in DOM to verify scroll target
    const targetDiv = document.createElement("div");
    targetDiv.id = "evidence-item-ev-text-1";
    targetDiv.scrollIntoView = vi.fn();
    document.body.appendChild(targetDiv);

    try {
      render(<CaseSummaryPanel currentCase={caseWithEvidence} />);

      expect(screen.getByTestId("case-summary-panel")).toBeInTheDocument();
      expect(screen.getByText(/False Urgency & Threat/i)).toBeInTheDocument();

      // Check evidence link anchor
      const links = screen.getAllByRole("link", { name: /Evidence: Bank Phishing SMS/i });
      expect(links.length).toBeGreaterThanOrEqual(1);
      const link = links[0]!;
      expect(link).toHaveAttribute("href", "#evidence-item-ev-text-1");

      // Verify clicking triggers scrollIntoView on target
      await user.click(link);
      expect(targetDiv.scrollIntoView).toHaveBeenCalled();
    } finally {
      document.body.removeChild(targetDiv);
    }
  });

  it("renders submitted URLs and quotes strictly as plain text (no clickable external links)", () => {
    const itemRep: EvidenceItem = {
      id: "ev-rep-1",
      sourceType: "url_reputation",
      title: "Threat Destination",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://phish.example.invalid/login",
        result: mockReputationThreatFresh,
        expires_at: mockReputationThreatFresh.expires_at ?? null,
        checked_at: mockReputationThreatFresh.checked_at,
        is_stale: false,
      },
    };

    const caseWithRep: Case = {
      id: "case-rep",
      name: "Reputation Case",
      createdAt: new Date().toISOString(),
      evidence: [itemRep],
    };

    render(<CaseSummaryPanel currentCase={caseWithRep} />);

    // Check plain text URL
    const urlCode = screen.getByTestId("summary-url-plain");
    expect(urlCode).toHaveTextContent("https://phish.example.invalid/login");

    // Ensure there are no outbound links with href="https://phish.example.invalid/login"
    const links = screen.queryAllByRole("link");
    const externalLinks = links.filter((l) =>
      l.getAttribute("href")?.startsWith("https://phish.example.invalid")
    );
    expect(externalLinks).toHaveLength(0);
  });

  it("treats expired reputation findings as historical in Warning Signs and What Remains Unknown", () => {
    const itemExpired: EvidenceItem = {
      id: "ev-expired-1",
      sourceType: "url_reputation",
      title: "Old Malicious Link",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://old-threat.example.invalid",
        result: mockReputationThreatExpired,
        expires_at: mockReputationThreatExpired.expires_at ?? null,
        checked_at: mockReputationThreatExpired.checked_at,
        is_stale: true,
      },
    };

    const caseExpired: Case = {
      id: "case-expired",
      name: "Expired Threat Case",
      createdAt: new Date().toISOString(),
      evidence: [itemExpired],
    };

    render(<CaseSummaryPanel currentCase={caseExpired} />);

    // 1. In Warning Signs, it must be flagged as Historical (Expired)
    expect(screen.getByText(/Historical \(Expired\)/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Google Safe Browsing previously reported this URL under threat categories/i)
    ).toBeInTheDocument();

    // 2. In What Remains Unknown, it must note that current threat status is unknown
    expect(screen.getByText(/Current Threat Status Unknown \(Expired Lookup\)/i)).toBeInTheDocument();
    expect(
      screen.getByText(/has expired or was captured over 30 minutes ago/i)
    ).toBeInTheDocument();
  });

  it("does not treat 'No Known Threat Matches' as a conflict against message warning signs", () => {
    const itemMsg: EvidenceItem = {
      id: "ev-msg-1",
      sourceType: "text_analysis",
      title: "Suspicious Offer",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Pay upfront registration fee",
        result: mockAnalysisWithWarnings,
      },
    };

    const itemCleanRep: EvidenceItem = {
      id: "ev-rep-clean",
      sourceType: "url_reputation",
      title: "Safe Browsing Check",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://clean-site.example.invalid",
        result: mockReputationClean,
        expires_at: mockReputationClean.expires_at ?? null,
        checked_at: mockReputationClean.checked_at,
        is_stale: false,
      },
    };

    const caseNonConflict: Case = {
      id: "case-nc",
      name: "Non Conflict Case",
      createdAt: new Date().toISOString(),
      evidence: [itemMsg, itemCleanRep],
    };

    render(<CaseSummaryPanel currentCase={caseNonConflict} />);

    // Verify Warning Signs shows the message warning sign
    expect(screen.getByText(/False Urgency & Threat/i)).toBeInTheDocument();

    // Verify Conflicting Findings explicitly states no conflicts
    expect(
      screen.getByText(/No direct conflicts identified in the saved evidence/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Findings are consistent/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/A “No Known Threat Matches” reputation lookup evaluates threat feed inclusion only and does not contradict warning signs in message text/i)
    ).toBeInTheDocument();
  });

  it("does not treat different assessments of different messages as a conflict", () => {
    const itemMsg1: EvidenceItem = {
      id: "ev-msg-diff-1",
      sourceType: "text_analysis",
      title: "Bank Urgent Lure",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Your bank account has been suspended immediately.",
        result: mockAnalysisWithWarnings,
      },
    };

    const itemMsg2: EvidenceItem = {
      id: "ev-msg-diff-2",
      sourceType: "text_analysis",
      title: "Doctor Appointment Reminder",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Reminder: Your annual checkup is tomorrow at 10 AM.",
        result: mockAnalysisClean,
      },
    };

    const caseDifferentMessages: Case = {
      id: "case-diff-msg",
      name: "Different Messages Case",
      createdAt: new Date().toISOString(),
      evidence: [itemMsg1, itemMsg2],
    };

    render(<CaseSummaryPanel currentCase={caseDifferentMessages} />);

    // Warning signs from the first message must be present
    expect(screen.getByText(/False Urgency & Threat/i)).toBeInTheDocument();

    // Must NOT flag a conflict because they are different messages
    expect(screen.queryByText(/Incompatible Assessments/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/No direct conflicts identified in the saved evidence/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Findings are consistent/i)).not.toBeInTheDocument();
  });

  it("identifies genuine conflicts when incompatible claims are made about the exact same message text", () => {
    const identicalText = "Your account has been suspended. Please confirm your credentials.";

    const itemWarn: EvidenceItem = {
      id: "ev-same-w",
      sourceType: "text_analysis",
      title: "Analysis Flagging Threat",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: identicalText,
        result: mockAnalysisWithWarnings,
      },
    };

    const itemClean: EvidenceItem = {
      id: "ev-same-c",
      sourceType: "text_analysis",
      title: "Analysis Clear",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: identicalText,
        result: mockAnalysisClean,
      },
    };

    const caseSameMessage: Case = {
      id: "case-same-msg",
      name: "Same Message Conflict Case",
      createdAt: new Date().toISOString(),
      evidence: [itemWarn, itemClean],
    };

    render(<CaseSummaryPanel currentCase={caseSameMessage} />);

    expect(screen.getByText(/Incompatible Assessments for Identical Message Text/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Two analyses evaluated the exact same message text under comparable conditions with contradictory conclusions/i)
    ).toBeInTheDocument();

    // Verify links to both conflicting evidence items
    const links = screen.getAllByRole("link", { name: /Evidence #/i });
    expect(links.length).toBeGreaterThanOrEqual(2);
  });

  it("does not treat Safe Browsing match and no-match for the same URL as a conflict when checked at different times, presenting them as temporal observations with timestamps", () => {
    const targetUrl = "https://example.invalid/update";
    const earlierTimestamp = "2026-11-13T10:00:00.000Z";
    const laterTimestamp = "2026-11-13T12:00:00.000Z";

    const itemEarlierMatch: EvidenceItem = {
      id: "ev-rep-earlier-match",
      sourceType: "url_reputation",
      title: "Morning Safe Browsing Lookup",
      addedAt: earlierTimestamp,
      payload: {
        sourceType: "url_reputation",
        url: targetUrl,
        result: {
          ...mockReputationThreatFresh,
          checked_url: targetUrl,
          checked_at: earlierTimestamp,
        },
        checked_at: earlierTimestamp,
        expires_at: "2026-11-13T10:10:00.000Z", // expired lookup
        is_stale: true,
      },
    };

    const itemLaterClean: EvidenceItem = {
      id: "ev-rep-later-clean",
      sourceType: "url_reputation",
      title: "Noon Safe Browsing Lookup",
      addedAt: laterTimestamp,
      payload: {
        sourceType: "url_reputation",
        url: targetUrl,
        result: {
          ...mockReputationClean,
          checked_url: targetUrl,
          checked_at: laterTimestamp,
        },
        checked_at: laterTimestamp,
        expires_at: new Date(Date.now() + 600000).toISOString(),
        is_stale: false,
      },
    };

    const caseTemporal: Case = {
      id: "case-temporal",
      name: "Temporal Observation Case",
      createdAt: laterTimestamp,
      evidence: [itemEarlierMatch, itemLaterClean],
    };

    render(<CaseSummaryPanel currentCase={caseTemporal} />);

    // 1. Must NOT be reported as a conflict
    expect(
      screen.getByText(/No direct conflicts identified in the saved evidence/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Findings are consistent/i)).not.toBeInTheDocument();

    // 2. Must be presented as Observations Over Time
    const temporalContainer = screen.getByTestId("summary-temporal-observations");
    expect(temporalContainer).toBeInTheDocument();
    expect(screen.getByText(/Observations Over Time/i)).toBeInTheDocument();
    expect(screen.getByTestId("summary-temporal-url")).toHaveTextContent(targetUrl);

    // 3. Both observations with timestamps must be present
    expect(screen.getByText(`Checked: ${earlierTimestamp}`)).toBeInTheDocument();
    expect(screen.getByText(`Checked: ${laterTimestamp}`)).toBeInTheDocument();

    // 4. Status badges inside temporal observations
    expect(within(temporalContainer).getByText(/^threat match$/i)).toBeInTheDocument();
    expect(within(temporalContainer).getByText(/^no known match$/i)).toBeInTheDocument();

    // 5. Expired status on earlier check
    expect(screen.getAllByText(/Historical \(Expired\)/i).length).toBeGreaterThanOrEqual(1);

    // 6. Navigation anchors to evidence cards within temporal observations
    expect(
      within(temporalContainer).getByRole("link", { name: /Evidence: Morning Safe Browsing Lookup/i })
    ).toHaveAttribute("href", "#evidence-item-ev-rep-earlier-match");
    expect(
      within(temporalContainer).getByRole("link", { name: /Evidence: Noon Safe Browsing Lookup/i })
    ).toHaveAttribute("href", "#evidence-item-ev-rep-later-clean");
  });

  it("compares submitted message text exactly and does not flag a conflict when texts differ in casing or whitespace", () => {
    const itemMsgExact: EvidenceItem = {
      id: "ev-msg-exact-1",
      sourceType: "text_analysis",
      title: "Mixed Case Message",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Your Account Is Suspended.",
        result: mockAnalysisWithWarnings,
      },
    };

    const itemMsgDifferentSpacing: EvidenceItem = {
      id: "ev-msg-exact-2",
      sourceType: "text_analysis",
      title: "Lowercase Spaced Message",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "your account is  suspended.",
        result: mockAnalysisClean,
      },
    };

    const caseExactComparison: Case = {
      id: "case-exact-comparison",
      name: "Exact Comparison Case",
      createdAt: new Date().toISOString(),
      evidence: [itemMsgExact, itemMsgDifferentSpacing],
    };

    render(<CaseSummaryPanel currentCase={caseExactComparison} />);

    // Because texts differ in case and whitespace, exact comparison must not treat them as identical
    expect(
      screen.getByText(/No direct conflicts identified in the saved evidence/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Incompatible Assessments for Identical Message Text/i)).not.toBeInTheDocument();
  });

  it("does not treat Safe Browsing match and no-match for the same URL as a conflict when checked_at is identical, expecting zero conflicts while preserving both evidence records", () => {
    const targetUrl = "https://example.invalid/concurrent-test";
    const sameTimestamp = new Date(Date.now() - 60000).toISOString();

    const itemMatch: EvidenceItem = {
      id: "ev-rep-same-match",
      sourceType: "url_reputation",
      title: "Concurrent Provider Feed A",
      addedAt: sameTimestamp,
      payload: {
        sourceType: "url_reputation",
        url: targetUrl,
        result: {
          ...mockReputationThreatFresh,
          checked_url: targetUrl,
          checked_at: sameTimestamp,
        },
        checked_at: sameTimestamp,
        expires_at: new Date(Date.now() + 600000).toISOString(),
        is_stale: false,
      },
    };

    const itemNoMatch: EvidenceItem = {
      id: "ev-rep-same-clean",
      sourceType: "url_reputation",
      title: "Concurrent Provider Feed B",
      addedAt: sameTimestamp,
      payload: {
        sourceType: "url_reputation",
        url: targetUrl,
        result: {
          ...mockReputationClean,
          checked_url: targetUrl,
          checked_at: sameTimestamp,
        },
        checked_at: sameTimestamp,
        expires_at: new Date(Date.now() + 600000).toISOString(),
        is_stale: false,
      },
    };

    const caseConcurrent: Case = {
      id: "case-concurrent",
      name: "Concurrent Disagreement Case",
      createdAt: sameTimestamp,
      evidence: [itemMatch, itemNoMatch],
    };

    render(<CaseSummaryPanel currentCase={caseConcurrent} />);

    // 1. Both evidence records are preserved in the case
    expect(caseConcurrent.evidence).toHaveLength(2);

    // 2. Expect zero conflicts
    expect(
      screen.getByText(/No direct conflicts identified in the saved evidence/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Contradictory Concurrent Reputation/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Incompatible Assessments/i)).not.toBeInTheDocument();

    // 3. Warning sign from the threat match is preserved
    expect(screen.getByText(/Safe Browsing Threat Match/i)).toBeInTheDocument();
  });

  it("presents practical verification steps including primary trusted-channel guidance", () => {
    const itemMsg: EvidenceItem = {
      id: "ev-msg",
      sourceType: "text_analysis",
      title: "Phishing SMS",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "text_analysis",
        submittedText: "Suspicious message",
        result: mockAnalysisWithWarnings,
      },
    };

    const caseSteps: Case = {
      id: "case-steps",
      name: "Steps Case",
      createdAt: new Date().toISOString(),
      evidence: [itemMsg],
    };

    render(<CaseSummaryPanel currentCase={caseSteps} />);

    // Primary trusted channel verification
    expect(
      screen.getByText(/Contact the claimed organization directly through an independent, verified channel you already trust/i)
    ).toBeInTheDocument();

    // Specific step from analysis
    expect(
      screen.getByText(/Call the bank using the phone number on your physical card/i)
    ).toBeInTheDocument();
  });
});

describe("generateCaseSummary unit logic", () => {
  it("handles structural flags and missing reputation checks", () => {
    const itemStruct: EvidenceItem = {
      id: "ev-struct-1",
      sourceType: "url_structure",
      title: "Userinfo URL",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "url_structure",
        url: "https://mybank.com@malicious.example.invalid/login",
        result: mockUrlInspection,
      },
    };

    const testCase: Case = {
      id: "case-struct",
      name: "Structure Only Case",
      createdAt: new Date().toISOString(),
      evidence: [itemStruct],
    };

    const summary = generateCaseSummary(testCase, Date.now());

    expect(summary.hasEvidence).toBe(true);
    // Structural flag appears in warning signs
    expect(summary.warningSigns).toHaveLength(1);
    expect(summary.warningSigns[0]?.title).toContain("Embedded Userinfo Credentials");

    // Missing reputation check appears in unknowns
    const unknownRep = summary.unknowns.find((u) => u.title.includes("External Reputation Not Checked"));
    expect(unknownRep).toBeDefined();
  });
});
