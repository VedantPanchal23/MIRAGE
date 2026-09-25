"""FastAPI Gateway Application Entrypoint."""

import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from db.mongo import MongoPersistenceError
from db.persistence import DatabasePersistenceError
from db.redis import RedisServiceError, default_redis_client_manager
from gateway.middleware.pii import PIIDetectionMiddleware
from gateway.middleware.security import HeaderSanitizationMiddleware, SecurityHeadersMiddleware
from gateway.routes.alerts import router as alerts_router
from gateway.routes.audit import router as audit_router
from gateway.routes.dashboard import router as dashboard_router
from gateway.routes.health import router as health_router
from gateway.routes.knowledge_base import router as knowledge_base_router
from gateway.routes.proxy import router as proxy_router
from gateway.routes.reports import router as reports_router
from gateway.routes.sessions import router as sessions_router
from gateway.routes.stream import router as stream_router
from gateway.routes.verify import router as verify_router
from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.telemetry import export_metrics, record_request_metric
from shared.tracing import configure_tracer

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle hook initializing logging, tracing, and closing connections on exit."""
    configure_logging(
        service_name="mirage-gateway",
        log_level=settings.log_level,
        json_format=settings.environment.value != "development",
    )
    configure_tracer(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
    )
    logger = get_logger("gateway")
    logger.info("MIRAGE Gateway initialized", version="2.1.0", environment=settings.environment.value)
    yield
    await default_redis_client_manager.close()
    logger.info("MIRAGE Gateway shutdown complete")


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="MIRAGE Factual Consistency Verification Gateway",
        description=(
            "Autonomous Multimodal Hallucination Detection & Factual Consistency "
            "Verification Middleware for Production LLMs"
        ),
        version="2.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. PII Detection Middleware (Pre-processing scanner, non-blocking)
    app.add_middleware(PIIDetectionMiddleware)

    # 3. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["https://dashboard.mirage-ai.internal"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 4. Header Sanitization Middleware (Strips untrusted client headers e.g. X-Role at ASGI boundary)
    app.add_middleware(HeaderSanitizationMiddleware)

    # 4. Request Telemetry Middleware
    @app.middleware("http")
    async def request_telemetry_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start_time = time.time()
        tenant_id = request.headers.get("X-Tenant-ID", "anonymous")
        response = await call_next(request)
        _ = time.time() - start_time
        endpoint = request.url.path
        # Avoid exploding cardinality on dynamic paths
        if endpoint.startswith("/v1/dashboard/sessions"):
            endpoint = "/v1/dashboard/sessions"
        record_request_metric(tenant_id=tenant_id, status_code=response.status_code, endpoint=endpoint)
        return response

    # 5. Mount Prometheus Metrics Endpoint
    @app.get("/metrics", tags=["Observability"], include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus metrics scrape target."""
        data, content_type = export_metrics()
        return Response(content=data, media_type=content_type)

    # 6. Mount API Routers
    app.include_router(health_router)
    app.include_router(verify_router)
    app.include_router(proxy_router)
    app.include_router(stream_router)
    app.include_router(dashboard_router)
    app.include_router(knowledge_base_router)
    app.include_router(audit_router)
    app.include_router(sessions_router)
    app.include_router(alerts_router)
    app.include_router(reports_router)

    # 7. Global Error Handlers
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            422: "UNPROCESSABLE_ENTITY",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_SERVER_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        error_code = code_map.get(exc.status_code, "ERROR")
        content: dict[str, Any] = {
            "detail": exc.detail,
            "error": {
                "code": error_code,
                "message": str(exc.detail),
                "trace_id": trace_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }
        headers = dict(exc.headers) if exc.headers else {}
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        content: dict[str, Any] = {
            "detail": exc.errors(),
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request schema or parameters",
                "details": exc.errors(),
                "trace_id": trace_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content)

    @app.exception_handler(DatabasePersistenceError)
    async def database_persistence_exception_handler(request: Request, exc: DatabasePersistenceError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger = get_logger("gateway")
        logger.error("Authoritative PostgreSQL persistence unavailable", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Authoritative database persistence is unavailable. Verification transaction aborted.",
                "error": {
                    "code": "SERVICE_DEGRADED",
                    "message": "Authoritative database persistence is unavailable. Verification transaction aborted.",
                    "details": {"error": str(exc)},
                    "trace_id": trace_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
        )

    @app.exception_handler(MongoPersistenceError)
    async def mongo_persistence_exception_handler(request: Request, exc: MongoPersistenceError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger = get_logger("gateway")
        logger.error("Authoritative MongoDB trace persistence unavailable", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Authoritative trace persistence is unavailable. Verification transaction aborted.",
                "error": {
                    "code": "SERVICE_DEGRADED",
                    "message": "Authoritative trace persistence is unavailable. Verification transaction aborted.",
                    "details": {"error": str(exc)},
                    "trace_id": trace_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
        )

    @app.exception_handler(RedisServiceError)
    async def redis_service_exception_handler(request: Request, exc: RedisServiceError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger = get_logger("gateway")
        logger.error("Redis service failure", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Rate limiting service is unavailable. Request rejected for system stability.",
                "error": {
                    "code": "SERVICE_DEGRADED",
                    "message": "Rate limiting service is unavailable. Request rejected for system stability.",
                    "details": {"error": str(exc)},
                    "trace_id": trace_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
            headers={"Retry-After": "10"},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger = get_logger("gateway")
        logger.error("Unhandled gateway exception", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal error occurred during verification.",
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An internal error occurred during verification.",
                    "trace_id": trace_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
        )

    return app


app = create_app()
