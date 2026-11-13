import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CaseBuilder } from "../features/case/CaseBuilder";
import { Case, EvidenceItem } from "../types/case";
import { TextAnalysisResponse, UrlInspectionResponse, UrlReputationResponse } from "../types/api";

const mockTextAnalysisResult: TextAnalysisResponse = {
  assessment: "warning_signs_found",
  category: "job",
  summary: "The message demands an upfront registration fee for a remote job.",
  warning_signs: [
    {
      title: "Advance Fee Requirement",
      evidence_quote: "transfer a refundable registration deposit of $150",
      explanation: "Legitimate employers never require candidates to pay fees.",
    },
  ],
  uncertainties: ["Sender organization could not be verified."],
  verification_steps: ["Contact the company through official channels."],
  language: "en",
  analysis_basis: "submitted_text_only",
  external_checks_performed: false,
  limitation: "AI assessment evaluates textual content only.",
};

const mockUrlInspectionResult: UrlInspectionResponse = {
  submitted_url: "https://secure-login.example.com/auth",
  scheme: "https",
  hostname: "secure-login.example.com",
  hostname_ascii: "secure-login.example.com",
  hostname_unicode: "secure-login.example.com",
  port: null,
  is_default_port: true,
  path: "/auth",
  query: null,
  fragment: null,
  has_userinfo: false,
  userinfo: null,
  is_ip_address: false,
  ip_version: null,
  ip_scope: null,
  is_punycode: false,
  registrable_domain: "example.com",
  subdomain_count: 1,
  subdomains: ["secure-login"],
  observations: [
    {
      id: "deep_subdomain",
      title: "Deep Subdomain",
      level: "caution",
      description: "Subdomain hierarchy observed.",
    },
  ],
  summary: "Evaluated URL structure.",
  inspection_basis: "local_heuristics_only",
  external_checks_performed: false,
  notice: "Local structural analysis.",
  limitation: "Does not contact server.",
};

const mockReputationResultFresh: UrlReputationResponse = {
  status: "no_known_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: [],
  checked_url: "https://example.com/safe",
  checked_at: new Date(Date.now() - 60000).toISOString(), // 1 minute ago
  expires_at: new Date(Date.now() + 300000).toISOString(), // expires in 5 minutes
  is_cached: false,
  is_stale: false,
  summary: "No threat match found on Google Safe Browsing lists.",
  advisory: "No known threat match does not guarantee safety.",
  attribution: "Data provided by Google Safe Browsing.",
};

const mockReputationResultThreat: UrlReputationResponse = {
  status: "threat_match",
  provider: "Google Safe Browsing (v4)",
  threat_types: ["MALWARE", "SOCIAL_ENGINEERING"],
  checked_url: "https://malicious.example.com",
  checked_at: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
  expires_at: new Date(Date.now() - 1800000).toISOString(), // expired 30 minutes ago
  is_cached: false,
  is_stale: true,
  summary: "Google Safe Browsing returned 2 threat matches.",
  advisory: "Warning: High risk destination.",
  attribution: "Data provided by Google Safe Browsing.",
};

describe("CaseBuilder Component", () => {
  it("renders creation form and in-memory reminder when no case exists", () => {
    const handleCreate = vi.fn();
    const handleDelete = vi.fn();
    const handleRemove = vi.fn();

    render(
      <CaseBuilder
        currentCase={null}
        onCreateCase={handleCreate}
        onDeleteCase={handleDelete}
        onRemoveEvidence={handleRemove}
      />
    );

    expect(screen.getByRole("heading", { name: /Case Builder/i })).toBeInTheDocument();
    expect(screen.getByText(/In-Memory Storage Only/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Create a New Case/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create Case/i })).toBeInTheDocument();
  });

  it("validates non-empty case name upon submission", async () => {
    const user = userEvent.setup();
    const handleCreate = vi.fn();

    render(
      <CaseBuilder
        currentCase={null}
        onCreateCase={handleCreate}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    const submitBtn = screen.getByRole("button", { name: /Create Case/i });
    await user.click(submitBtn);

    expect(screen.getByText(/Please enter a case name\./i)).toBeInTheDocument();
    expect(handleCreate).not.toHaveBeenCalled();

    const input = screen.getByLabelText(/Create a New Case/i);
    await user.type(input, "Phishing Telegram SMS");
    await user.click(submitBtn);

    expect(handleCreate).toHaveBeenCalledWith("Phishing Telegram SMS");
  });

  it("renders active case header, in-memory notice, and empty evidence state", () => {
    const activeCase: Case = {
      id: "case-123",
      name: "Investigation Case Alpha",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    render(
      <CaseBuilder
        currentCase={activeCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    expect(screen.getByTestId("active-case-name")).toHaveTextContent("Investigation Case Alpha");
    expect(screen.getByText(/0 evidence items/i)).toBeInTheDocument();
    expect(screen.getByTestId("no-evidence-message")).toHaveTextContent(
      /No evidence items added yet/i
    );
    expect(screen.getByRole("button", { name: /Delete Case/i })).toBeInTheDocument();
  });

  it("triggers onDeleteCase when Delete Case button is clicked", async () => {
    const user = userEvent.setup();
    const handleDelete = vi.fn();

    const activeCase: Case = {
      id: "case-123",
      name: "Investigation Case Alpha",
      createdAt: new Date().toISOString(),
      evidence: [],
    };

    render(
      <CaseBuilder
        currentCase={activeCase}
        onCreateCase={vi.fn()}
        onDeleteCase={handleDelete}
        onRemoveEvidence={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: /Delete Case/i }));
    expect(handleDelete).toHaveBeenCalledTimes(1);
  });

  it("renders all 4 evidence source types with plain text and distinct labels", () => {
    const evidenceItems: EvidenceItem[] = [
      {
        id: "ev-1",
        sourceType: "text_analysis",
        title: "Suspicious Job Message",
        addedAt: new Date().toISOString(),
        payload: {
          sourceType: "text_analysis",
          submittedText: "Deposit $150 to registration@example.invalid immediately.",
          result: mockTextAnalysisResult,
        },
      },
      {
        id: "ev-2",
        sourceType: "extracted_text",
        title: "Screenshot OCR Text",
        addedAt: new Date().toISOString(),
        payload: {
          sourceType: "extracted_text",
          extractionType: "screenshot",
          fileName: "screenshot_telegram.png",
          extractedText: "Your account is temporarily suspended. Click to verify.",
        },
      },
      {
        id: "ev-3",
        sourceType: "url_structure",
        title: "URL Structure (secure-login.example.com)",
        addedAt: new Date().toISOString(),
        payload: {
          sourceType: "url_structure",
          url: "https://secure-login.example.com/auth",
          result: mockUrlInspectionResult,
        },
      },
      {
        id: "ev-4",
        sourceType: "url_reputation",
        title: "Safe Browsing: No Known Match",
        addedAt: new Date().toISOString(),
        payload: {
          sourceType: "url_reputation",
          url: "https://example.com/safe",
          result: mockReputationResultFresh,
          expires_at: mockReputationResultFresh.expires_at ?? null,
          checked_at: mockReputationResultFresh.checked_at,
          is_stale: false,
        },
      },
    ];

    const activeCase: Case = {
      id: "case-123",
      name: "Comprehensive Investigation",
      createdAt: new Date().toISOString(),
      evidence: evidenceItems,
    };

    render(
      <CaseBuilder
        currentCase={activeCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    // 1. Text Analysis Evidence
    expect(screen.getByText("Message Analysis")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-message-text")).toHaveTextContent(
      "Deposit $150 to registration@example.invalid immediately."
    );
    expect(screen.getByText("Warning Signs Detected")).toBeInTheDocument();

    // 2. Extracted Text Evidence
    expect(screen.getByText("Extracted Text")).toBeInTheDocument();
    expect(screen.getByText("Local OCR (Screenshot)")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-extracted-text")).toHaveTextContent(
      "Your account is temporarily suspended. Click to verify."
    );

    // 3. URL Structure Evidence
    expect(screen.getByText("URL Structure")).toBeInTheDocument();
    expect(
      screen.getByText("URL Structural Inspection (Local Syntax Analysis)")
    ).toBeInTheDocument();
    expect(screen.getByTestId("evidence-url-structure-plain")).toHaveTextContent(
      "https://secure-login.example.com/auth"
    );

    // 4. URL Reputation Evidence
    expect(screen.getByText("Safe Browsing Reputation")).toBeInTheDocument();
    expect(
      screen.getByText("URL Threat Reputation (Google Safe Browsing)")
    ).toBeInTheDocument();
    expect(screen.getByTestId("evidence-reputation-url-plain")).toHaveTextContent(
      "https://example.com/safe"
    );
    expect(screen.getByText("No Known Threat Matches")).toBeInTheDocument();
    expect(screen.getByText(/Data provided by Google Safe Browsing/i)).toBeInTheDocument();

    // Check that URLs and extracted content are plain text (no <a> tags pointing to target URLs)
    const links = screen.queryAllByRole("link");
    const targetUrlLinks = links.filter((link) =>
      link.getAttribute("href")?.includes("example.com")
    );
    expect(targetUrlLinks).toHaveLength(0);
  });

  it("displays stale badge when reputation evidence has expired or is stale", async () => {
    const staleEvidence: EvidenceItem = {
      id: "ev-stale",
      sourceType: "url_reputation",
      title: "Safe Browsing: Threat Match",
      addedAt: new Date().toISOString(),
      payload: {
        sourceType: "url_reputation",
        url: "https://malicious.example.com",
        result: mockReputationResultThreat,
        expires_at: mockReputationResultThreat.expires_at ?? null,
        checked_at: mockReputationResultThreat.checked_at,
        is_stale: true,
      },
    };

    const activeCase: Case = {
      id: "case-stale",
      name: "Stale Reputation Case",
      createdAt: new Date().toISOString(),
      evidence: [staleEvidence],
    };

    render(
      <CaseBuilder
        currentCase={activeCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("evidence-stale-badge")).toBeInTheDocument();
    });
    expect(screen.getByTestId("evidence-stale-badge")).toHaveTextContent(
      /Stale Reputation Finding/i
    );
    expect(screen.getByText("Threat Match Detected")).toBeInTheDocument();
    expect(screen.getByText("MALWARE")).toBeInTheDocument();
    expect(screen.getByText("SOCIAL_ENGINEERING")).toBeInTheDocument();
  });

  it("calls onRemoveEvidence with the item id when Remove Item button is clicked", async () => {
    const user = userEvent.setup();
    const handleRemove = vi.fn();

    const activeCase: Case = {
      id: "case-123",
      name: "Removal Test Case",
      createdAt: new Date().toISOString(),
      evidence: [
        {
          id: "item-to-remove",
          sourceType: "text_analysis",
          title: "Item 1",
          addedAt: new Date().toISOString(),
          payload: {
            sourceType: "text_analysis",
            submittedText: "test message",
            result: mockTextAnalysisResult,
          },
        },
      ],
    };

    render(
      <CaseBuilder
        currentCase={activeCase}
        onCreateCase={vi.fn()}
        onDeleteCase={vi.fn()}
        onRemoveEvidence={handleRemove}
      />
    );

    const removeBtn = screen.getByRole("button", { name: /Remove evidence Item 1/i });
    await user.click(removeBtn);

    expect(handleRemove).toHaveBeenCalledWith("item-to-remove");
  });
});
