from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

AssessmentType = Literal[
    "warning_signs_found",
    "no_clear_warning_signs",
    "insufficient_information",
]

CategoryType = Literal[
    "job",
    "phishing",
    "shopping_payment",
    "other",
    "unclear",
]

LanguageType = Literal["en", "hi"]


class TextAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        ...,
        description="Message text to analyze. Must be non-empty and up to 10,000 characters.",
    )
    language: LanguageType = Field(
        default="en",
        description="Preferred explanation language. Supported: 'en' (English), 'hi' (Hindi).",
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Text cannot be empty or contain only whitespace.")
        if len(trimmed) > 10000:
            raise ValueError("Text exceeds maximum allowed length of 10,000 characters.")
        return trimmed


class WarningSign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=150, description="Short title of the warning sign.")
    evidence_quote: str = Field(
        ...,
        max_length=500,
        description="Exact verbatim excerpt from the submitted message that supports this warning sign.",
    )
    explanation: str = Field(
        ...,
        max_length=1000,
        description="Explanation in the requested language of why this excerpt raises concern.",
    )

    @field_validator("title", "evidence_quote", "explanation")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed


class WarningSignProviderSchema(BaseModel):
    """Structured warning sign item."""
    title: str = Field(
        description="Short title of the warning sign."
    )
    evidence_quote: str = Field(
        description="Exact verbatim excerpt from the submitted message that supports this warning sign."
    )
    explanation: str = Field(
        description="Explanation in the requested language of why this excerpt raises concern."
    )


class AnalysisProviderOutputSchema(BaseModel):
    """Structured assessment output schema for Gemini generation."""
    assessment: Literal[
        "warning_signs_found",
        "no_clear_warning_signs",
        "insufficient_information",
    ] = Field(
        description="Overall assessment: warning_signs_found, no_clear_warning_signs, or insufficient_information."
    )
    category: Literal[
        "job",
        "phishing",
        "shopping_payment",
        "other",
        "unclear",
    ] = Field(
        description="Scam category: job, phishing, shopping_payment, other, or unclear."
    )
    summary: str = Field(
        description="Concise summary explanation in the requested language."
    )
    warning_signs: List[WarningSignProviderSchema] = Field(
        description="List of concrete warning signs backed by exact verbatim quotes. Must be empty if no_clear_warning_signs."
    )
    uncertainties: List[str] = Field(
        description="Aspects the message cannot establish (e.g. sender identity, unregistered entities)."
    )
    verification_steps: List[str] = Field(
        description="Practical, safe steps the user should take independently to verify."
    )
    language: Literal["en", "hi"] = Field(
        description="Language in which explanations were generated (en or hi)."
    )


class AnalysisModelOutput(BaseModel):
    """
    Strict application-side schema enforced on Gemini generated JSON output.
    Extra fields are strictly forbidden, length bounds and list constraints are enforced.
    """
    model_config = ConfigDict(extra="forbid")

    assessment: AssessmentType = Field(
        ...,
        description="Overall assessment: warning_signs_found, no_clear_warning_signs, or insufficient_information.",
    )
    category: CategoryType = Field(
        ...,
        description="Scam category: job, phishing, shopping_payment, other, or unclear.",
    )
    summary: str = Field(
        ...,
        max_length=1000,
        description="Concise summary explanation in the requested language.",
    )
    warning_signs: List[WarningSign] = Field(
        default_factory=list,
        max_length=10,
        description="List of concrete warning signs backed by exact verbatim quotes. Must be empty if no_clear_warning_signs.",
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Aspects the message cannot establish (e.g. sender identity, unregistered entities).",
    )
    verification_steps: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Practical, safe steps the user should take independently to verify.",
    )
    language: LanguageType = Field(
        ...,
        description="Language in which explanations were generated (en or hi).",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Summary cannot be empty.")
        return trimmed

    @field_validator("uncertainties", "verification_steps")
    @classmethod
    def validate_list_items(cls, items: List[str]) -> List[str]:
        cleaned = []
        for item in items:
            t = item.strip()
            if t:
                if len(t) > 500:
                    raise ValueError("List item exceeds 500 character limit.")
                cleaned.append(t)
        return cleaned


class TextAnalysisResponse(BaseModel):
    """
    Public API response for POST /api/v1/analyze/text.
    Includes the model's structured findings and application-controlled metadata.
    """
    model_config = ConfigDict(extra="forbid")

    assessment: AssessmentType
    category: CategoryType
    summary: str
    warning_signs: List[WarningSign]
    uncertainties: List[str]
    verification_steps: List[str]
    language: LanguageType

    # Application-controlled metadata outside model authority
    analysis_basis: Literal["submitted_text_only"] = "submitted_text_only"
    external_checks_performed: bool = False
    limitation: str = (
        "This assessment is generated by an AI model based solely on the submitted text. "
        "It does not constitute proof of fraud or legitimacy, and no external databases, "
        "identity registries, or live URLs were checked."
    )


class ErrorDetail(BaseModel):
    loc: List[str]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    reason: Optional[str] = None
    action: Optional[str] = None
    details: Optional[List[ErrorDetail]] = None
