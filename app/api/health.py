"""Health check endpoints."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.ollama_service import OllamaError, get_ollama_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    """Returns overall service health including Ollama connectivity."""
    settings = get_settings()
    ollama_service = get_ollama_service()

    ollama_status = "ok"
    ollama_version = None
    ollama_models = []

    try:
        version_info = await ollama_service.health_check()
        ollama_version = version_info.get("version", "unknown")
        models_raw = await ollama_service.list_models()
        ollama_models = [m.get("name", "") for m in models_raw]
    except OllamaError as exc:
        logger.warning("Ollama health check failed: %s", exc)
        ollama_status = "unavailable"

    overall = "ok" if ollama_status == "ok" else "degraded"

    return JSONResponse(
        status_code=200,
        content={
            "status": overall,
            "services": {
                "api": "ok",
                "ollama": {
                    "status": ollama_status,
                    "base_url": settings.ollama_base_url,
                    "version": ollama_version,
                    "active_model": settings.ollama_model,
                    "available_models": ollama_models,
                },
            },
        },
    )
