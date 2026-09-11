"""FastAPI Gateway Application Entrypoint."""

import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.middleware.security import SecurityHeadersMiddleware
from gateway.routes.dashboard import router as dashboard_router
from gateway.routes.health import router as health_router
from gateway.routes.proxy import router as proxy_router
from gateway.routes.stream import router as stream_router
from gateway.routes.verify import router as verify_router
from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.telemetry import export_metrics, record_request_metric
from shared.tracing import configure_tracer

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle hook initializing logging and tracing."""
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

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["https://dashboard.mirage-ai.internal"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 3. Request Telemetry Middleware
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

    # 4. Mount Prometheus Metrics Endpoint
    @app.get("/metrics", tags=["Observability"], include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus metrics scrape target."""
        data, content_type = export_metrics()
        return Response(content=data, media_type=content_type)

    # 5. Mount API Routers
    app.include_router(health_router)
    app.include_router(verify_router)
    app.include_router(proxy_router)
    app.include_router(stream_router)
    app.include_router(dashboard_router)

    # 6. Global Error Handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger = get_logger("gateway")
        logger.error("Unhandled gateway exception", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An internal error occurred during verification.",
                    "trace_id": trace_id,
                }
            },
        )

    return app


app = create_app()
