from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class DocumentPageInfo(BaseModel):
    page_number: int = Field(..., description="1-indexed page number.")
    has_text: bool = Field(..., description="Whether extractable text was found on this page.")
    char_count: int = Field(..., description="Character count of text extracted from this page.")


class DocumentExtractionResponse(BaseModel):
    combined_text: str = Field(
        ...,
        description="Extracted and normalized embedded text from all document pages.",
    )
    page_count: int = Field(..., description="Total number of pages in the PDF document.")
    char_count: int = Field(..., description="Total character count of combined extracted text.")
    extraction_method: Literal["embedded_text"] = Field(
        default="embedded_text",
        description="Extraction method applied (embedded text parsing).",
    )
    empty_pages: List[int] = Field(
        default_factory=list,
        description="Page numbers that contained no extractable text.",
    )
    warning: Optional[str] = Field(
        default=None,
        description="Visibly formatted warning if some pages lacked extractable text.",
    )
    pages: List[DocumentPageInfo] = Field(
        default_factory=list,
        description="Per-page extraction summary information.",
    )
    review_required: bool = Field(
        default=True,
        description="Human-in-the-loop review confirmation is required before downstream analysis.",
    )
    notice: str = Field(
        default=(
            "Analysis evaluates the submitted reviewed text only. Findings concern textual content, "
            "not document authenticity, signatures, visual tampering, sender identity, or URL reputation."
        ),
        description="Legal and analytical provenance notice.",
    )
    limitation: str = Field(
        default=(
            "Extraction evaluates embedded text only. Images, signatures, layout, and image-only "
            "text are not evaluated."
        ),
        description="Document extraction limitation notice.",
    )


class DocumentExtractionErrorResponse(BaseModel):
    code: str = Field(..., description="Application-specific safe error code.")
    message: str = Field(..., description="Sanitized human-readable error description.")
    action: Optional[str] = Field(default=None, description="Recommended user remediation action.")
    page_count: Optional[int] = Field(default=None, description="Page count if relevant to error.")
    char_count: Optional[int] = Field(default=None, description="Character count if relevant to error.")
    reason: Optional[str] = Field(default=None, description="Safe diagnostic sub-reason code.")
