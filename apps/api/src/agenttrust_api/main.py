"""FastAPI application factory with structured errors, request IDs, and CORS."""

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .deps import AppError
from .routers import (
    agent,
    agents,
    approvals,
    dashboard,
    evaluations,
    events,
    health,
    incidents,
    keys,
    metrics,
    policies,
    runs,
    toolcalls,
    tools,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request and echo it back in the response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _error(
    request: Request, error_code: str, message: str, status: int, retryable: bool = False
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error_code": error_code,
            "message": message,
            "request_id": _request_id(request),
            "retryable": retryable,
        },
    )


def create_app() -> FastAPI:
    from .config import settings as _settings

    # Interactive docs are a development aid (Phase 8 audit LOW-9): disable
    # them when deployed as production.
    _is_prod = _settings.AGENTTRUST_ENV.lower() == "production"
    app = FastAPI(
        title="AgentTrust API",
        version="0.1.0",
        docs_url=None if _is_prod else "/docs",
        openapi_url=None if _is_prod else "/openapi.json",
    )

    app.add_middleware(RequestIDMiddleware)

    origins = [o.strip() for o in settings.AGENTTRUST_CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error(request, exc.error_code, exc.message, exc.status_code, exc.retryable)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(request, f"http_{exc.status_code}", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(request, "validation_error", "Request validation failed.", 422)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error(request, "internal_error", "Unexpected server error.", 500)

    @app.get("/", tags=["health"])
    def index() -> dict:
        return {"service": "agenttrust-api", "version": "0.1.0", "docs": "/docs"}

    app.include_router(health.router)
    app.include_router(keys.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(policies.router, prefix="/api/v1")
    app.include_router(toolcalls.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(evaluations.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    return app


app = create_app()
