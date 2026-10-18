"""Liveness and readiness probes."""

from fastapi import APIRouter
from sqlalchemy import text

from ..db import engine
from ..deps import AppError
from ..schemas import HealthLiveResponse, HealthReadyResponse
from ..util import utcnow

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthLiveResponse)
def live() -> HealthLiveResponse:
    """Liveness: the process is running. Performs no dependency checks."""
    return HealthLiveResponse(timestamp=utcnow())


@router.get("/health/ready", response_model=HealthReadyResponse)
def ready() -> HealthReadyResponse:
    """Readiness: the process is running AND PostgreSQL answers a ping."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise AppError(
            "database_unavailable", "Database is not reachable.", 503, retryable=True
        ) from exc
    return HealthReadyResponse(timestamp=utcnow())
