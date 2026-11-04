import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UrlInspector } from "../features/url/UrlInspector";
import * as api from "../lib/api";
import { UrlInspectionResponse } from "../types/api";

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

describe("UrlInspector Component", () => {
  it("renders heading, input, and Inspect button in initial state", () => {
    render(<UrlInspector />);

    expect(
      screen.getByRole("heading", { name: "URL Structure Inspection", level: 2 })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/URL to Inspect/i)).toBeInTheDocument();

    const inspectBtn = screen.getByRole("button", { name: "Inspect URL" });
    expect(inspectBtn).toBeInTheDocument();
    expect(inspectBtn).toBeDisabled();
  });

  it("updates character counter and enables Inspect button when URL is entered", () => {
    render(<UrlInspector />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com" } });

    expect(screen.getByText(/19 \/ 2,048 characters/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect URL" })).toBeEnabled();
  });

  it("successfully inspects a URL and prominently displays destination host and plain text URL", async () => {
    const inspectMock = vi.spyOn(api, "inspectUrl").mockResolvedValueOnce(mockSuccessResponse);

    render(<UrlInspector />);

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

    render(<UrlInspector />);

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

    render(<UrlInspector />);

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

    render(<UrlInspector />);

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

    render(<UrlInspector />);

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

    render(<UrlInspector />);

    const input = screen.getByLabelText(/URL to Inspect/i);
    fireEvent.change(input, { target: { value: "https://example.com/initial" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect URL" }));

    expect(screen.getByText("Inspecting Structure...")).toBeInTheDocument();

    // User types new text while request is in flight
    fireEvent.change(input, { target: { value: "https://example.com/changed" } });

    // Resolve the previous late request
    resolvePromise!(mockSuccessResponse);

    // Result must NOT be rendered because the request was canceled/superceded
    await waitFor(() => {
      expect(screen.queryByTestId("url-inspection-results")).not.toBeInTheDocument();
    });
  });
});
