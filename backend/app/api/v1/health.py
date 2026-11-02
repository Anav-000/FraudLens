from fastapi import APIRouter
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
def get_health() -> HealthResponse:
    """
    Checks if the backend API service is running.
    Does not test external AI availability.
    """
    return HealthResponse(status="ok", service="fraudlens-api")
