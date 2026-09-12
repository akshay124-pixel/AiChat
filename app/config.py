"""
Application configuration — all values driven by environment variables.
Never hardcode secrets or URLs; change them in .env or Docker environment.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ollama ──────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout: int = 120          # seconds; raise for slow VPS / large models

    # ── FastAPI ─────────────────────────────────────────────────────────────
    app_title: str = "AI Chat API"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── CORS ─────────────────────────────────────────────────────────────────
    # List of allowed origins — must include your exact Vercel URL in production
    # e.g. '["https://your-app.vercel.app"]'
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # ── In-memory conversation store limits ──────────────────────────────────
    max_conversations: int = 500
    max_messages_per_conversation: int = 200


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
