import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UrlInspector } from "../features/url/UrlInspector";
import * as api from "../lib/api";
import {
  BackendConnectionState,
  UrlInspectionResponse,
  UrlReputationResponse,
} from "../types/api";

const mockSuccessResponse: UrlInspectionResponse = {
  submitted_url: "https://example.com/login?step=1",
  scheme: "https",
  hostname: "example.com",
  hostname_ascii: "example.com",
  hostname_unicode: "example.com",
  port: null,
  is_default_port: true,
  path: "/login",
  query: "step=1",
  fragment: null,
  has_userinfo: false,
  userinfo: null,
  is_ip_address: false,
  ip_version: null,
  ip_scope: null,
  is_punycode: false,
  registrable_domain: "example.com",
  subdomain_count: 0,
  subdomains: [],
  observations: [],
  summary: "Valid HTTPS URL pointing to destination host 'example.com'. No unusual structural characteristics detected.",
  inspection_basis: "url_structure_only",
  external_checks_performed: false,
  notice: "URL Structure Inspection Only — No external reputation checks, domain registration lookups, or live network connections performed.",
  limitation: "This assessment is based solely on local structural analysis of the submitted URL string.",
};

const mockUserinfoResponse: UrlInspectionResponse = {
  ...mockSuccessResponse,
  submitted_url: "https://mybank.com@destination.invalid/account",
  hostname: "destination.invalid",
  hostname_ascii: "destination.invalid",
  hostname_unicode: "destination.invalid",
  has_userinfo: true,
  userinfo: "mybank.com",
  registrable_domain: "destination.invalid",
  observations: [
    {
      id: "userinfo_present",
      title: "Embedded Authentication / Userinfo in Netloc",
      level: "caution",
      description: "The URL includes userinfo credentials ('mybank.com') before an '@' delimiter.",
    },
  ],
};

const mockConnectedState: BackendConnectionState = {
  status: "connected",
  capabilities: {
    text_analysis: true,
    screenshot_extraction: false,
    document_extraction: true,
    url_inspection: true,
    url_reputation: true,
    saved_cases: false,
    ai_connection: "not_tested",
    ai_configuration: "present",
  },
};

const mockUnconfiguredState: BackendConnectionState = {
  status: "connected",
  capabilities: {
    ...mockConnectedState.capabilities,
    url_reputation: false,
  },
};

const mockThreatMatchResponse: UrlReputationResponse = {
  status: "threat_match",
  provider: "Google Safe Browsing",
  threat_types: ["MALWARE", "SOCIAL_ENGINEERING"],
  checked_url: "https://example.com/phish",
  get checked_at() {
    return new Date().toISOString();
  },
  expires_at: null,
  is_cached: false,
  is_stale: false,
  summary: "Google Safe Browsing reported this URL matches known threat categories: MALWARE, SOCIAL_ENGINEERING.",
  advisory: "Advisory: Google Safe Browsing lists may not include all dangerous websites, and threat statuses can change rapidly. An absence of findings does not guarantee safety. Do not rely on Safe Browsing as a guarantee of legitimacy.",
  attribution: "Data provided by Google Safe Browsing.",
  error_code: null,
  error_message: null,
  error_reason: null,
  error_action: null,
};

const mockNoMatchResponse: UrlReputationResponse = {
  status: "no_known_match",
  provider: "Google Safe Browsing",
  threat_types: [],
  checked_url: "https://example.com/clean",
  get checked_at() {
    return new Date().toISOString();
  },
  get expires_at() {
    return new Date(Date.now() + 1800000).toISOString();
  },
  is_cached: false,
  is_stale: false,
  summary: "No known threat match was returned. This does not prove the URL is safe.",
  advisory: "Advisory: Google Safe Browsing lists may not include all dangerous websites, and threat statuses can change rapidly. An absence of findings does not guarantee safety. Do not rely on Safe Browsing as a guarantee of legitimacy.",
  attribution: "Data provided by Google Safe Browsing.",
  error_code: null,
  error_message: null,
  error_reason: null,
  error_action: null,
};

describe("UrlInspector Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ---------------------------------------------------------------------------
  // Phase 4A Tests (Offline URL Structure Inspection)
  // ---------------------------------------------------------------------------

  it("renders heading, input, and Inspect button in initial state", () => {
    render(<UrlInspector backendState={mockConnectedState} />);

    expect(
      screen.getByRole("heading", { name: /URL Structure Inspection/i, level: 2 })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/URL to Inspect/i)).toBeInTheDocument();

    const inspectBtn = screen.getByRole("button", { name: "Inspect URL" });
    expect(inspectBtn).toBeInTheDocument();
    expect(inspectBtn).toBeDisabled();
  });

  it("updates character counter and enables Inspect button when URL is entered", () => {
    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com" } });

    expect(screen.getByText(/19 \/ 2,048 characters/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect URL" })).toBeEnabled();
  });

  it("successfully inspects a URL and prominently displays destination host and plain text URL", async () => {
    const inspectMock = vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockSuccessResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/login?step=1" } });

    const inspectBtn = screen.getByRole("button", { name: "Inspect URL" });
    fireEvent.click(inspectBtn);

    expect(screen.getByText("Inspecting Structure...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("url-inspection-results")).toBeInTheDocument();
    });

    expect(inspectMock).toHaveBeenCalledWith(
      "https://example.com/login?step=1",
      expect.any(AbortSignal)
    );

    // Verify prominent destination host display
    expect(screen.getByText("Actual Destination Hostname")).toBeInTheDocument();
    expect(screen.getByTestId("destination-hostname")).toHaveTextContent("example.com");

    // Verify submitted URL is rendered as plain text, NOT an anchor tag
    const plainUrlEl = screen.getByTestId("submitted-url-plain");
    expect(plainUrlEl).toBeInTheDocument();
    expect(plainUrlEl.tagName.toLowerCase()).not.toBe("a");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    // Verify breakdown and notices
    expect(screen.getByText(/HTTPS scheme — connection not checked/i)).toBeInTheDocument();
    expect(screen.getByText(/No structural anomalies detected/i)).toBeInTheDocument();
    expect(screen.getByText(/URL Structure Inspection Only/i)).toBeInTheDocument();
  });

  it("highlights userinfo credentials warning when credentials precede destination host", async () => {
    vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockUserinfoResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://mybank.com@destination.invalid/account" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    await waitFor(() => {
      expect(screen.getByTestId("destination-hostname")).toHaveTextContent("destination.invalid");
    });

    // Check userinfo notice
    expect(screen.getByText(/Warning: Userinfo in URL/i)).toBeInTheDocument();
    expect(screen.getAllByText(/mybank\.com/).length).toBeGreaterThan(0);
    expect(screen.getByText("Embedded Authentication / Userinfo in Netloc")).toBeInTheDocument();
  });

  it("displays error callout with code and actionable advice on failure", async () => {
    vi.spyOn(api, "inspectUrl").mockRejectedValueOnce(
      new api.ApiClientError(
        "URL scheme 'ftp' is unsupported. Only explicit 'http' and 'https' schemes are supported.",
        false,
        false,
        "UNSUPPORTED_SCHEME",
        "Provide a URL that uses 'https://' or 'http://'.",
        422
      )
    );

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "ftp://files.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText(/URL Inspection Failed/i)).toBeInTheDocument();
    expect(screen.getByText("UNSUPPORTED_SCHEME")).toBeInTheDocument();
    expect(screen.getByText(/URL scheme 'ftp' is unsupported/i)).toBeInTheDocument();
    expect(screen.getByText(/Advice: Provide a URL that uses 'https:\/\/' or 'http:\/\/'/i)).toBeInTheDocument();
  });

  it("marks result as stale when input text is edited after inspection", async () => {
    vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockSuccessResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/login?step=1" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    await waitFor(() => {
      expect(screen.getByTestId("url-inspection-results")).toBeInTheDocument();
    });

    // Edit the input URL
    fireEvent.change(input, { target: { value: "https://example.com/login?step=2" } });

    // Verify stale notification
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/Input modified:/i)).toBeInTheDocument();
  });

  it("clears all state and results when Reset is clicked", async () => {
    vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockSuccessResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/login" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    await waitFor(() => {
      expect(screen.getByTestId("url-inspection-results")).toBeInTheDocument();
    });

    const resetBtn = screen.getByRole("button", { name: "Reset" });
    fireEvent.click(resetBtn);

    expect(input).toHaveValue("");
    expect(screen.queryByTestId("url-inspection-results")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("discards late responses if input is changed while inspection is in flight", async () => {
    let resolvePromise: (value: UrlInspectionResponse) => void;
    const delayedPromise = new Promise<UrlInspectionResponse>((resolve) => {
      resolvePromise = resolve;
    });

    vi.spyOn(api, "inspectUrl").mockReturnValueOnce(delayedPromise);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/initial" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    expect(screen.getByText("Inspecting Structure...")).toBeInTheDocument();

    // User types new text while request is in flight
    fireEvent.change(input, { target: { value: "https://example.com/changed" } });

    // Resolve the previous late request
    await act(async () => {
      resolvePromise!(mockSuccessResponse);
    });

    // Result must NOT be rendered because the request was canceled/superceded
    expect(screen.queryByTestId("url-inspection-results")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Phase 4B Tests (Optional Google Safe Browsing URL Reputation)
  // ---------------------------------------------------------------------------

  it("previews exact URL sent to Google (fragments stripped) and requires explicit consent", async () => {
    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://target-destination.com/login?token=xyz#admin" } });

    // Preview must display URL with fragment stripped
    const previewEl = screen.getByTestId("preview-url-plain");
    expect(previewEl).toHaveTextContent("https://target-destination.com/login?token=xyz");
    expect(previewEl).not.toHaveTextContent("#admin");

    // Privacy notice must be conspicuously present
    expect(screen.getByText(/Privacy Notice:/i)).toBeInTheDocument();

    // Consent checkbox must be UNCHECKED by default
    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL to Google Safe Browsing/i,
    });
    expect(consentCheckbox).not.toBeChecked();

    // Check Reputation button must initially be disabled
    const checkRepBtn = screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i });
    expect(checkRepBtn).toBeDisabled();

    // Check consent -> button enables
    fireEvent.click(consentCheckbox);
    expect(consentCheckbox).toBeChecked();
    expect(checkRepBtn).toBeEnabled();
  });

  it("displays informative notice and disables reputation button when Safe Browsing is unconfigured", () => {
    render(<UrlInspector backendState={mockUnconfiguredState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/test" } });

    // Informative unconfigured notice
    expect(screen.getByText(/Google Safe Browsing Unconfigured on Server/i)).toBeInTheDocument();

    // Consent and Check Reputation button must remain disabled
    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    expect(consentCheckbox).toBeDisabled();

    const checkRepBtn = screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i });
    expect(checkRepBtn).toBeDisabled();

    // Offline inspection button must remain enabled
    expect(screen.getByRole("button", { name: "Inspect URL" })).toBeEnabled();
  });

  it("checks reputation and displays Threat Match with attribution and advisory", async () => {
    const repMock = vi.spyOn(api, "checkUrlReputation").mockResolvedValueOnce(mockThreatMatchResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/phish#top" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);

    const checkRepBtn = screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i });
    fireEvent.click(checkRepBtn);

    expect(screen.getByRole("button", { name: /Checking Reputation.../i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    expect(repMock).toHaveBeenCalledWith(
      "https://example.com/phish#top",
      true,
      expect.any(AbortSignal)
    );

    // Verify threat match badge & reported categories
    expect(screen.getByText("Threat Match Detected")).toBeInTheDocument();
    expect(screen.getByText("MALWARE")).toBeInTheDocument();
    expect(screen.getByText("SOCIAL_ENGINEERING")).toBeInTheDocument();

    // Verify checked URL is rendered as plain text (NEVER a clickable link)
    const checkedUrlEl = screen.getByTestId("reputation-checked-url");
    expect(checkedUrlEl).toHaveTextContent("https://example.com/phish");
    expect(checkedUrlEl.tagName.toLowerCase()).not.toBe("a");
    expect(checkedUrlEl.querySelector("a")).toBeNull();

    // Official Google Safe Browsing attribution link (distinguished from inspected URLs)
    const attributionLink = screen.getByRole("link", { name: "Advisory provided by Google" });
    expect(attributionLink).toBeInTheDocument();
    expect(attributionLink).toHaveAttribute("href", "https://developers.google.com/safe-browsing/v4/advisory");
    expect(attributionLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(attributionLink).toHaveAttribute("target", "_blank");

    // The attribution link must be the ONLY link rendered (inspected URLs are non-clickable)
    expect(screen.getAllByRole("link")).toHaveLength(1);

    // Mandatory Safe Browsing advisory
    expect(screen.getByText(/Google Safe Browsing lists may not include all dangerous websites/i)).toBeInTheDocument();
  });

  it("checks reputation and displays No Known Match with explicit non-guarantee disclaimer", async () => {
    vi.spyOn(api, "checkUrlReputation").mockResolvedValueOnce(mockNoMatchResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/clean" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);

    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    // Qualified outcome: "No Known Threat Matches" (never claims "Safe")
    expect(screen.getByText("No Known Threat Matches")).toBeInTheDocument();
    expect(screen.getByText(/This does not prove the URL is safe/i)).toBeInTheDocument();
    const nomatchAttrLink = screen.getByRole("link", { name: "Advisory provided by Google" });
    expect(nomatchAttrLink).toBeInTheDocument();
    expect(nomatchAttrLink).toHaveAttribute("href", "https://developers.google.com/safe-browsing/v4/advisory");

    // Fresh result shown - NO immediate expiry banner
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();
  });

  it("handles reputation API error with safe machine-readable code and advice", async () => {
    vi.spyOn(api, "checkUrlReputation").mockRejectedValueOnce(
      new api.ApiClientError(
        "Private, loopback, or reserved IP destinations (127.0.0.1) cannot be submitted for external reputation checking.",
        false,
        false,
        "FORBIDDEN_DESTINATION",
        "Provide a URL pointing to a public domain name or public IP address.",
        422,
        "non_public_ip"
      )
    );

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "http://127.0.0.1:8080/admin" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);

    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByText(/Reputation Check Unavailable/i)).toBeInTheDocument();
    });

    expect(screen.getByText("FORBIDDEN_DESTINATION (non_public_ip)")).toBeInTheDocument();
    expect(screen.getByText(/Private, loopback, or reserved IP destinations/i)).toBeInTheDocument();
    expect(screen.getByText(/Advice: Provide a URL pointing to a public domain name/i)).toBeInTheDocument();
  });

  it("invalidates consent and marks previous reputation results stale on URL edit", async () => {
    vi.spyOn(api, "checkUrlReputation").mockResolvedValueOnce(mockThreatMatchResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/phish" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    expect(consentCheckbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    // User edits the URL input
    fireEvent.change(input, { target: { value: "https://example.com/phish-edited" } });

    // Consent must automatically be unchecked
    expect(consentCheckbox).not.toBeChecked();

    // Reputation results card must be marked stale with visible notice
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
    expect(screen.getByText(/Reputation Result Expired or Input Modified/i)).toBeInTheDocument();
  });

  it("discards late reputation response if input is edited while request is in flight", async () => {
    let resolvePromise: (value: UrlReputationResponse) => void;
    const delayedPromise = new Promise<UrlReputationResponse>((resolve) => {
      resolvePromise = resolve;
    });

    vi.spyOn(api, "checkUrlReputation").mockReturnValueOnce(delayedPromise);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/pending" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);

    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));
    expect(screen.getByRole("button", { name: /Checking Reputation.../i })).toBeInTheDocument();

    // User types into input while reputation lookup is in flight
    fireEvent.change(input, { target: { value: "https://example.com/changed" } });

    // Resolve late promise
    await act(async () => {
      resolvePromise!(mockThreatMatchResponse);
    });

    // Late result must NOT be rendered
    expect(screen.queryByTestId("reputation-results-card")).not.toBeInTheDocument();
  });

  it("automatically marks displayed reputation result stale after 30-minute deadline using fake timers", async () => {
    const fixedNow = 1700000000000;
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const freshReputation: UrlReputationResponse = {
      ...mockThreatMatchResponse,
      checked_at: new Date(fixedNow).toISOString(),
      expires_at: new Date(fixedNow + 1800000).toISOString(), // 30 minutes
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValue(freshReputation);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/test-stale" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);

    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    // Flush pending microtasks
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    // Initially not stale
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // Advance timers by 31 minutes (exceeds 30-minute warning freshness deadline)
    act(() => {
      vi.advanceTimersByTime(31 * 60 * 1000);
    });

    // Result must now visibly be flagged as stale
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
    expect(screen.getByText(/Reputation Result Expired or Input Modified/i)).toBeInTheDocument();
  });

  it("keeps no-match with expires_at=null fresh initially, marks stale after 30-minute display limit, and marks stale on URL edit", async () => {
    const fixedNow = 1700000000000;
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const noMatchNullExpiry: UrlReputationResponse = {
      ...mockNoMatchResponse,
      checked_at: new Date(fixedNow).toISOString(),
      expires_at: null,
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValue(noMatchNullExpiry);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/no-match-null-expiry" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    // Fresh result shown - NO immediate expiry banner
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // After 29 minutes: still fresh
    act(() => {
      vi.advanceTimersByTime(29 * 60 * 1000);
    });
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // After 30-minute display limit (31 minutes): marked stale
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 1000);
    });
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
    expect(screen.getByText(/Reputation Result Expired or Input Modified/i)).toBeInTheDocument();
  });

  it("marks fresh no-match result stale when URL input changes", async () => {
    const noMatchNullExpiry: UrlReputationResponse = {
      ...mockNoMatchResponse,
      expires_at: null,
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValue(noMatchNullExpiry);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/clean" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    // Initially fresh without expiry banner
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // Editing URL input marks reputation result stale immediately
    fireEvent.change(input, { target: { value: "https://example.com/clean-modified" } });
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
    expect(screen.getByText(/Reputation Result Expired or Input Modified/i)).toBeInTheDocument();
  });

  it("maintains strict independence between offline inspection and external reputation", async () => {
    const inspectSpy = vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockSuccessResponse);
    const repSpy = vi.spyOn(api, "checkUrlReputation").mockResolvedValueOnce(mockNoMatchResponse);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/page" } });

    // Click Inspect URL
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    await waitFor(() => {
      expect(screen.getByTestId("url-inspection-results")).toBeInTheDocument();
    });

    // Only inspectUrl called, zero Safe Browsing calls
    expect(inspectSpy).toHaveBeenCalledTimes(1);
    expect(repSpy).not.toHaveBeenCalled();

    // Now consent and click Check Reputation
    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    // Only 1 reputation check called, inspectUrl not called again
    expect(repSpy).toHaveBeenCalledTimes(1);
    expect(inspectSpy).toHaveBeenCalledTimes(1);
  });

  it("honors earlier of expires_at and checked_at + 30m, expiring after a short 5-minute deadline", async () => {
    const fixedNow = 1700000000000;
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const fiveMinReputation: UrlReputationResponse = {
      ...mockThreatMatchResponse,
      checked_at: new Date(fixedNow).toISOString(),
      expires_at: new Date(fixedNow + 5 * 60 * 1000).toISOString(), // 5 minutes
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValue(fiveMinReputation);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/short-expiry" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    // Initially not stale at t = 0
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // At 4 minutes: still fresh
    act(() => {
      vi.advanceTimersByTime(4 * 60 * 1000);
    });
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // At 5 minutes + 1s: expired via the earlier 5-minute expires_at (not 30m)
    act(() => {
      vi.advanceTimersByTime(61 * 1000);
    });
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
  });

  it("honors an incoming is_stale=true immediately upon rendering reputation response", async () => {
    const incomingStaleReputation: UrlReputationResponse = {
      ...mockNoMatchResponse,
      is_stale: true,
      summary: "Cached finding returned past freshness boundary.",
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValueOnce(incomingStaleReputation);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/already-stale" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await waitFor(() => {
      expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    });

    // Must be marked stale immediately upon arrival
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
    expect(screen.getByText(/Reputation Result Expired or Input Modified/i)).toBeInTheDocument();
  });

  it("rechecks freshness on tab visibility/focus restoration so suspended tabs do not display expired results", async () => {
    const fixedNow = 1700000000000;
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const fiveMinReputation: UrlReputationResponse = {
      ...mockThreatMatchResponse,
      checked_at: new Date(fixedNow).toISOString(),
      expires_at: new Date(fixedNow + 5 * 60 * 1000).toISOString(),
    };

    vi.spyOn(api, "checkUrlReputation").mockResolvedValue(fiveMinReputation);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/suspended-tab" } });

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("reputation-results-card")).toBeInTheDocument();
    expect(screen.queryByTestId("reputation-stale-notice")).not.toBeInTheDocument();

    // Simulate tab backgrounding: time advances 10 minutes while timers were frozen/throttled
    vi.setSystemTime(fixedNow + 10 * 60 * 1000);

    // Tab visibility restored: dispatch visibilitychange
    act(() => {
      Object.defineProperty(document, "visibilityState", { value: "visible", writable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Displayed result must immediately become stale upon visibility restoration
    expect(screen.getByTestId("reputation-stale-notice")).toBeInTheDocument();
  });

  it("aborted request resolving late cannot disturb a newer request or restore results after reset", async () => {
    let resolveReq1: (val: UrlReputationResponse) => void;
    let resolveReq2: (val: UrlReputationResponse) => void;
    const p1 = new Promise<UrlReputationResponse>((res) => { resolveReq1 = res; });
    const p2 = new Promise<UrlReputationResponse>((res) => { resolveReq2 = res; });

    const repSpy = vi.spyOn(api, "checkUrlReputation")
      .mockReturnValueOnce(p1)
      .mockReturnValueOnce(p2);

    render(<UrlInspector backendState={mockConnectedState} />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    const consentCheckbox = screen.getByRole("checkbox", {
      name: /I consent to transmitting this destination URL/i,
    });

    // 1. Start Request 1
    fireEvent.change(input, { target: { value: "https://example.com/first" } });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    // 2. Before Request 1 resolves, user changes URL and starts Request 2
    fireEvent.change(input, { target: { value: "https://example.com/second" } });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    expect(repSpy).toHaveBeenCalledTimes(2);

    // 3. Request 1 (obsolete) resolves late with threat match
    await act(async () => {
      resolveReq1({
        ...mockThreatMatchResponse,
        checked_url: "https://example.com/first",
        summary: "OBSOLETE RESULT 1",
      });
    });

    // Obsolete result must NOT be shown
    expect(screen.queryByText("OBSOLETE RESULT 1")).not.toBeInTheDocument();

    // 4. Request 2 resolves with no known match
    await act(async () => {
      resolveReq2({
        ...mockNoMatchResponse,
        checked_url: "https://example.com/second",
        summary: "CORRECT RESULT 2",
      });
    });

    // Correct result is displayed
    expect(screen.getByText("CORRECT RESULT 2")).toBeInTheDocument();

    // 5. Test Reset: user resets while a late error rejects
    let rejectReq3: (err: any) => void;
    const p3 = new Promise<UrlReputationResponse>((_, rej) => { rejectReq3 = rej; });
    vi.spyOn(api, "checkUrlReputation").mockReturnValueOnce(p3);

    fireEvent.change(input, { target: { value: "https://example.com/third" } });
    fireEvent.click(consentCheckbox);
    fireEvent.click(screen.getByRole("button", { name: /Check Reputation \(Safe Browsing\)/i }));

    // User clicks Reset while Request 3 is pending
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    // Request 3 rejects late with an error
    await act(async () => {
      rejectReq3(new api.ApiClientError("Late failure", false, false, "INTERNAL_ERROR", undefined, 500));
    });

    // Reset state must remain clean: no error callout, no results
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("reputation-results-card")).not.toBeInTheDocument();
  });
});