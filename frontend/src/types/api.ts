export type Language = "en" | "hi";
export type OcrLanguage = "eng" | "hin";

export interface HealthResponse {
  status: string;
  service: string;
}

export interface CapabilitiesResponse {
  text_analysis: boolean;
  screenshot_extraction: boolean;
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
