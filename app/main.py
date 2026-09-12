"""
FastAPI application entry point.
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import chat_router, conversations_router, health_router
from app.config import get_settings
from app.services.ollama_service import get_ollama_service

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS is set by nginx, not here
        return response


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting AI Chat API v%s  [env=%s  debug=%s]",
        settings.app_version,
        settings.environment,
        settings.debug,
    )
    logger.info("Ollama URL  : %s", settings.ollama_base_url)
    logger.info("Ollama model: %s", settings.ollama_model)
    logger.info("CORS origins: %s", settings.cors_origins)
    # Note: OLLAMA_BASE_URL is logged but it's just a URL, not a secret.

    yield

    ollama_service = get_ollama_service()
    await ollama_service.close()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="AI Chat backend — FastAPI + Ollama",
    lifespan=lifespan,
    # Docs are disabled in production (DEBUG=false)
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# ---------------------------------------------------------------------------
# Middleware — CORS first, then security headers
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# Global exception handler — never leak internals to the client
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(conversations_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "AI Chat API", "version": settings.app_version}
