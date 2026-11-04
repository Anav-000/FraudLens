from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

MAX_URL_LENGTH = 2048


class UrlObservationLevel(str, Enum):
    INFORMATIONAL = "informational"
    CAUTION = "caution"
    WARNING = "warning"


class UrlObservation(BaseModel):
    """
    Deterministic structural observation about a submitted URL.
    Observations reflect structural facts without asserting fraud or legitimacy.
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Machine-readable observation identifier.")
    title: str = Field(..., description="Human-readable title for the observation.")
    level: UrlObservationLevel = Field(..., description="Observation classification category.")
    description: str = Field(..., description="Objective, calibrated explanation of the observation.")


class UrlInspectionRequest(BaseModel):
    """
    Request payload for local URL structure inspection.
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        ...,
        min_length=1,
        max_length=MAX_URL_LENGTH,
        description="URL string to inspect locally (explicit http:// or https:// required).",
    )


class UrlInspectionResponse(BaseModel):
    """
    Structured outcome of local offline URL structure inspection.
    Provides verified destination host and structural properties without network lookups.
    """
    model_config = ConfigDict(extra="forbid")

    submitted_url: str = Field(..., description="Original submitted URL string.")
    scheme: str = Field(..., description="Normalized URL scheme (http or https).")
    hostname: str = Field(..., description="Extracted destination hostname.")
    hostname_ascii: str = Field(..., description="Punycode / ASCII representation of the hostname.")
    hostname_unicode: str = Field(..., description="Unicode representation of the hostname.")
    port: Optional[int] = Field(None, description="Explicit port number if present in the URL.")
    is_default_port: bool = Field(..., description="True if port is omitted or matches scheme default.")
    path: str = Field(..., description="Path component of the URL.")
    query: Optional[str] = Field(None, description="Query string if present in the URL.")
    fragment: Optional[str] = Field(None, description="Fragment identifier if present in the URL.")
    has_userinfo: bool = Field(..., description="True if credentials/userinfo precede the destination host.")
    userinfo: Optional[str] = Field(None, description="Userinfo component if present.")
    is_ip_address: bool = Field(..., description="True if destination host is an IPv4 or IPv6 address.")
    ip_version: Optional[int] = Field(None, description="4 or 6 if destination host is an IP address.")
    ip_scope: Optional[str] = Field(None, description="Scope classification if host is an IP address.")
    is_punycode: bool = Field(..., description="True if hostname contains IDNA punycode (xn--).")
    registrable_domain: Optional[str] = Field(None, description="Derived eTLD+1 using bundled offline Public Suffix List.")
    subdomain_count: int = Field(0, description="Count of subdomain labels preceding registrable domain.")
    subdomains: list[str] = Field(default_factory=list, description="Subdomain labels.")
    observations: list[UrlObservation] = Field(default_factory=list, description="Deterministic structural observations.")
    summary: str = Field(..., description="Calibrated summary of structural findings.")
    inspection_basis: str = Field(
        default="url_structure_only",
        description="Basis of the inspection: local URL structure parsing only.",
    )
    external_checks_performed: bool = Field(
        default=False,
        description="Always false: no DNS, HTTP, WHOIS, or reputation queries are performed.",
    )
    notice: str = Field(
        ...,
        description="User-facing notice regarding the offline, local nature of the inspection.",
    )
    limitation: str = Field(
        ...,
        description="Explicit limitation disclaimer stating that structural inspection cannot establish safety or fraud.",
    )


class UrlInspectionErrorResponse(BaseModel):
    """
    Sanitized error response for URL structure inspection failures.
    """
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="Standardized application error code.")
    message: str = Field(..., description="Sanitized human-readable error description.")
    action: str = Field(..., description="Actionable advice for the user.")
    reason: Optional[str] = Field(None, description="Specific sub-reason code if applicable.")
