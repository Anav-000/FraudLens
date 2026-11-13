from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from app.schemas.url_inspection import MAX_URL_LENGTH

MAX_WARNING_FRESHNESS_SECONDS = 1800  # 30 minutes (Google warning freshness rule)


ReputationStatus = Literal[
    "threat_match",
    "no_known_match",
    "unavailable",
    "not_checked",
]


class UrlReputationRequest(BaseModel):
    """
    Request model for Google Safe Browsing URL reputation check.
    Requires explicit user consent and URL string up to 2,048 characters.
    """
    url: str = Field(
        ...,
        min_length=1,
        max_length=MAX_URL_LENGTH,
        description="The HTTP or HTTPS URL to check against Google Safe Browsing.",
    )
    consent: bool = Field(
        ...,
        description="Explicit user consent to transmit the URL (including path and query parameters) to Google.",
    )


class UrlReputationResponse(BaseModel):
    """
    Structured outcome of optional Google Safe Browsing reputation check.
    Distinguishes threat matches, no known matches, and unavailable provider states.
    Always provides required Google Safe Browsing attribution and advisory notice.
    """
    status: ReputationStatus = Field(
        ...,
        description="Outcome category: 'threat_match', 'no_known_match', 'unavailable', or 'not_checked'.",
    )
    provider: str = Field(
        default="Google Safe Browsing",
        description="The threat intelligence provider queried.",
    )
    threat_types: List[str] = Field(
        default_factory=list,
        description="Categories of detected threats returned by Google Safe Browsing (e.g. MALWARE, SOCIAL_ENGINEERING).",
    )
    checked_url: str = Field(
        ...,
        description="The exact URL (with fragment stripped) transmitted to the Safe Browsing service.",
    )
    checked_at: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of when this assessment was performed or retrieved.",
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 UTC timestamp when this cached result expires according to provider cache duration.",
    )
    is_cached: bool = Field(
        default=False,
        description="Whether this result was served from the local expiring in-memory cache.",
    )
    is_stale: bool = Field(
        default=False,
        description="True if the finding is older than Google's 30-minute warning freshness threshold or past expiration.",
    )
    summary: str = Field(
        ...,
        description="Calibrated narrative summary of the reputation outcome.",
    )
    advisory: str = Field(
        default="Advisory: Google Safe Browsing lists may not include all dangerous websites, and threat statuses can change rapidly. An absence of findings does not guarantee safety. Do not rely on Safe Browsing as a guarantee of legitimacy.",
        description="Conspicuous user advisory required by Google Safe Browsing Terms of Service.",
    )
    attribution: str = Field(
        default="Data provided by Google Safe Browsing.",
        description="Mandatory Google Safe Browsing attribution notice.",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Diagnostic code if the provider check was unavailable or encountered an error.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Safe explanatory error message if unavailable.",
    )
    error_reason: Optional[str] = Field(
        default=None,
        description="Machine-readable sub-reason for unavailable status.",
    )
    error_action: Optional[str] = Field(
        default=None,
        description="Actionable user guidance if unavailable.",
    )

    def is_expired(self, as_of: Optional[datetime] = None) -> bool:
        """
        Determines whether this finding is older than Google's 30-minute warning freshness threshold
        or past its expiration timestamp.
        """
        now = as_of or datetime.now(timezone.utc)
        if self.expires_at:
            try:
                exp_dt = datetime.fromisoformat(self.expires_at)
                if now >= exp_dt:
                    return True
            except (ValueError, TypeError):
                pass
        try:
            checked_dt = datetime.fromisoformat(self.checked_at)
            if (now - checked_dt).total_seconds() > MAX_WARNING_FRESHNESS_SECONDS:
                return True
        except (ValueError, TypeError):
            pass
        return self.is_stale

    def mark_stale_if_expired(self, as_of: Optional[datetime] = None) -> "UrlReputationResponse":
        """
        Returns a copy of the response with is_stale set to True if past the freshness deadline.
        """
        if self.is_expired(as_of):
            return self.model_copy(update={"is_stale": True})
        return self


class UrlReputationErrorResponse(BaseModel):
    """
    Sanitized error response for reputation checking validation and client errors.
    Never reflects sensitive credentials or private URL query tokens.
    """
    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="User-safe error explanation.")
    action: str = Field(..., description="Actionable next step for the user.")
    reason: Optional[str] = Field(default=None, description="Detailed diagnostic reason code.")
