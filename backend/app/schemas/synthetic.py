import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class SyntheticGreetingResponse(BaseModel):
    """
    Schema for synthetic smoke-test responses.
    Fictional content only; used strictly for verifying SDK structured output and connectivity.
    """
    status: Literal["ok"] = Field(
        ...,
        description="Verification status indicator, must be 'ok'."
    )
    english: str = Field(
        ...,
        min_length=1,
        description="Brief synthetic English greeting."
    )
    hindi: str = Field(
        ...,
        min_length=1,
        description="Brief synthetic Hindi greeting."
    )

    @field_validator("english")
    @classmethod
    def validate_english(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("English greeting cannot be empty or whitespace only.")
        return trimmed

    @field_validator("hindi")
    @classmethod
    def validate_hindi(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Hindi greeting cannot be empty or whitespace only.")
        return trimmed

    def has_hindi_script(self) -> bool:
        """
        Basic format check verifying the presence of Devanagari script characters (U+0900 to U+097F).
        Note: This is a format presence verification, not proof of translation quality.
        """
        return bool(re.search(r"[\u0900-\u097F]", self.hindi))
