"""
Application configuration.

All values are read from environment variables (or .env file).
Nothing is hardcoded — change behaviour by setting env vars.

Docker on VPS:
  OLLAMA_BASE_URL=http://host.docker.internal:11434  ← reaches host Ollama
  CORS_ORIGINS=["https://your-app.vercel.app"]

Local dev (uvicorn on host):
  OLLAMA_BASE_URL=http://localhost:11434
  CORS_ORIGINS=["http://localhost:5173"]
"""
from functools import lru_cache
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ollama ───────────────────────────────────────────────────────────────
    # In Docker on VPS: http://host.docker.internal:11434
    # In local dev:     http://localhost:11434
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout: int = 120

    # ── FastAPI ──────────────────────────────────────────────────────────────
    app_title: str = "AI Chat API"
    app_version: str = "1.0.0"
    # Set DEBUG=true only for local dev — enables /docs /redoc /openapi.json
    debug: bool = False
    # Used in logs to distinguish environments
    environment: Literal["development", "production"] = "production"

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Must include your exact Vercel URL in production.
    # Example: '["https://your-app.vercel.app"]'
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # ── In-memory store limits ────────────────────────────────────────────────
    max_conversations: int = 500
    max_messages_per_conversation: int = 200


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
