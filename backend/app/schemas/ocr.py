from typing import Literal, Optional
from pydantic import BaseModel, Field

OcrLanguage = Literal["eng", "hin"]


class ScreenshotExtractionResponse(BaseModel):
    """
    Response schema for successful screenshot text extraction.
    Instructs the frontend and user that OCR text requires review.
    """
    extracted_text: str = Field(
        ...,
        description="Raw text extracted from the screenshot by the local OCR engine."
    )
    ocr_language: OcrLanguage = Field(
        ...,
        description="OCR language used for character recognition ('eng' or 'hin')."
    )
    character_count: int = Field(
        ...,
        description="Length of extracted text in Unicode characters."
    )
    review_required: bool = Field(
        default=True,
        description="Indicates that the extracted text must be reviewed and verified by the user before analysis."
    )
    notice: str = Field(
        default=(
            "Please review and edit the extracted text. "
            "OCR may misread names, amounts, URLs, or characters."
        ),
        description="Guidance on reviewing OCR output before submission to analysis."
    )


class ExtractionErrorResponse(BaseModel):
    """
    Sanitized error response for extraction failures.
    Never exposes subprocess stderr, internal file paths, or stack traces.
    """
    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable explanation of what went wrong.")
    action: str = Field(..., description="Actionable recommendation for the user.")
    reason: Optional[str] = Field(default=None, description="Optional diagnostic classification.")
