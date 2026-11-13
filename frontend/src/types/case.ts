import {
  TextAnalysisResponse,
  UrlInspectionResponse,
  UrlReputationResponse,
} from "./api";

export type EvidenceSourceType =
  | "text_analysis"
  | "extracted_text"
  | "url_structure"
  | "url_reputation";

export interface TextAnalysisPayload {
  sourceType: "text_analysis";
  submittedText: string;
  result: TextAnalysisResponse;
}

export interface ExtractedTextPayload {
  sourceType: "extracted_text";
  extractionType: "screenshot" | "document";
  fileName?: string;
  extractedText: string;
}

export interface UrlStructurePayload {
  sourceType: "url_structure";
  url: string;
  result: UrlInspectionResponse;
}

export interface UrlReputationPayload {
  sourceType: "url_reputation";
  url: string;
  result: UrlReputationResponse;
  expires_at: string | null;
  checked_at: string;
  is_stale: boolean;
}

export type EvidencePayload =
  | TextAnalysisPayload
  | ExtractedTextPayload
  | UrlStructurePayload
  | UrlReputationPayload;

export interface EvidenceItem {
  id: string;
  sourceType: EvidenceSourceType;
  title: string;
  addedAt: string; // ISO date string
  payload: EvidencePayload;
}

export interface Case {
  id: string;
  name: string;
  createdAt: string; // ISO date string
  evidence: EvidenceItem[];
}
