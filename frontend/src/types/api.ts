export type Language = "en" | "hi";
export type OcrLanguage = "eng" | "hin";

export interface HealthResponse {
  status: string;
  service: string;
}

export interface CapabilitiesResponse {
  text_analysis: boolean;
  screenshot_extraction: boolean;
  document_extraction?: boolean;
  url_inspection?: boolean;
  url_reputation: boolean;
  saved_cases: boolean;
  ai_connection: "not_tested" | "connected" | "failed";
  ai_configuration: "missing" | "present";
  ocr_languages?: string[];
  ocr_prerequisite_status?: string;
}

export interface ScreenshotExtractionResponse {
  extracted_text: string;
  ocr_language: OcrLanguage;
  character_count: number;
  review_required: boolean;
  notice: string;
}

export interface DocumentPageInfo {
  page_number: number;
  has_text: boolean;
  char_count: number;
}

export interface DocumentExtractionResponse {
  combined_text: string;
  page_count: number;
  char_count: number;
  extraction_method: "embedded_text";
  empty_pages: number[];
  warning?: string | null;
  pages: DocumentPageInfo[];
  review_required: boolean;
  notice: string;
  limitation: string;
}

export type UrlObservationLevel = "informational" | "caution" | "warning";

export interface UrlObservation {
  id: string;
  title: string;
  level: UrlObservationLevel;
  description: string;
}

export interface UrlInspectionResponse {
  submitted_url: string;
  scheme: string;
  hostname: string;
  hostname_ascii: string;
  hostname_unicode: string;
  port: number | null;
  is_default_port: boolean;
  path: string;
  query: string | null;
  fragment: string | null;
  has_userinfo: boolean;
  userinfo: string | null;
  is_ip_address: boolean;
  ip_version: number | null;
  ip_scope: string | null;
  is_punycode: boolean;
  registrable_domain: string | null;
  subdomain_count: number;
  subdomains: string[];
  observations: UrlObservation[];
  summary: string;
  inspection_basis: string;
  external_checks_performed: boolean;
  notice: string;
  limitation: string;
}

export interface BackendCheckResult {
  health: HealthResponse;
  capabilities: CapabilitiesResponse;
}

export type BackendConnectionState =
  | { status: "checking" }
  | { status: "connected"; capabilities: CapabilitiesResponse }
  | { status: "unavailable"; errorMessage: string };

export type AssessmentType =
  | "warning_signs_found"
  | "no_clear_warning_signs"
  | "insufficient_information";

export type CategoryType =
  | "job"
  | "phishing"
  | "shopping_payment"
  | "other"
  | "unclear";

export interface WarningSign {
  title: string;
  evidence_quote: string;
  explanation: string;
}

export interface TextAnalysisResponse {
  assessment: AssessmentType;
  category: CategoryType;
  summary: string;
  warning_signs: WarningSign[];
  uncertainties: string[];
  verification_steps: string[];
  language: Language;
  analysis_basis: string;
  external_checks_performed: boolean;
  limitation: string;
}

export interface AnalysisErrorDetail {
  code: string;
  message: string;
  reason?: string;
  action?: string;
  stage?: string;
  exception_class?: string;
  http_status?: number | null;
  provider_status?: string | null;
}

export interface AnalysisErrorResponse {
  code?: string;
  message?: string;
  reason?: string;
  action?: string;
  error?: AnalysisErrorDetail;
  detail?: AnalysisErrorDetail | string;
}
