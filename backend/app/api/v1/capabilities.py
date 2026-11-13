from fastapi import APIRouter, Depends
from app.core.config import Settings, get_settings
from app.schemas.capabilities import CapabilitiesResponse
from app.services.ocr import check_ocr_availability

router = APIRouter()


@router.get("/capabilities", response_model=CapabilitiesResponse, tags=["Capabilities"])
def get_capabilities(
    settings: Settings = Depends(get_settings),
) -> CapabilitiesResponse:
    """
    Returns implemented system capabilities and safe configuration presence flags.
    Never exposes secrets, API keys, or tests live external connections.
    """
    has_provider = bool(settings.ai_provider and settings.ai_provider.strip().lower() != "none")
    has_key = settings.is_ai_key_configured()
    config_present = has_provider and has_key

    ocr_available, ocr_languages, ocr_status = check_ocr_availability(settings.tesseract_cmd)

    return CapabilitiesResponse(
        text_analysis=True,
        screenshot_extraction=ocr_available,
        document_extraction=True,
        url_inspection=True,
        url_reputation=settings.is_safe_browsing_configured(),
        saved_cases=False,
        ai_connection="not_tested",
        ai_configuration="present" if config_present else "missing",
        ocr_languages=ocr_languages,
        ocr_prerequisite_status=ocr_status,
    )
