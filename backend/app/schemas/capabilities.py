from typing import Literal
from pydantic import BaseModel


class CapabilitiesResponse(BaseModel):
    text_analysis: bool = True
    screenshot_extraction: bool = False
    url_reputation: bool = False
    saved_cases: bool = False
    ai_connection: Literal["not_tested", "connected", "failed"] = "not_tested"
    ai_configuration: Literal["missing", "present"] = "missing"
    ocr_languages: list[str] = []
    ocr_prerequisite_status: str = "unavailable"
