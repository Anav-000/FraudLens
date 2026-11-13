from functools import lru_cache
from pathlib import Path
from typing import List, Union
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine backend directory location independent of current working directory
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BACKEND_DIR / ".env"

PLACEHOLDER_KEYS = {
    "",
    "your-api-key-here",
    "your_key_here",
    "replace_me",
    "none",
    "placeholder",
}


class Settings(BaseSettings):
    """
    Application configuration for FraudLens backend.
    Secrets and AI credentials remain backend-only and are never exposed via endpoints.
    """
    environment: str = "development"
    allowed_origins: Union[List[str], str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    ai_provider: str = "none"
    ai_model: str = "gemini-3.5-flash-lite"
    ai_api_key: SecretStr | None = None
    tesseract_cmd: str | None = None
    safe_browsing_api_key: SecretStr | None = None
    safe_browsing_version: str = "v5"

    @field_validator("safe_browsing_version")
    @classmethod
    def validate_safe_browsing_version(cls, value: str) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("v4", "v5"):
                return normalized
        raise ValueError("safe_browsing_version must be either 'v4' or 'v5'")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Union[List[str], str]) -> List[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def is_ai_key_configured(self) -> bool:
        """
        Validates whether a non-empty, non-placeholder AI API key is configured.
        """
        if self.ai_api_key is None:
            return False
        raw_key = self.ai_api_key.get_secret_value().strip()
        if not raw_key:
            return False
        if raw_key.lower() in PLACEHOLDER_KEYS:
            return False
        return True

    def is_safe_browsing_configured(self) -> bool:
        """
        Validates whether a non-empty, non-placeholder Safe Browsing API key is configured.
        Truthfully reflects configuration without asserting that the key is verified to work.
        """
        if self.safe_browsing_api_key is None:
            return False
        raw_key = self.safe_browsing_api_key.get_secret_value().strip()
        if not raw_key:
            return False
        if raw_key.lower() in PLACEHOLDER_KEYS:
            return False
        return True

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
