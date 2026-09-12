"""
Ollama service layer.

This is the ONLY place in the codebase that communicates with Ollama.
Swap this file to change the LLM provider without touching any other code.

Connection architecture:
  Local dev:  OLLAMA_BASE_URL=http://localhost:11434
  Docker/VPS: OLLAMA_BASE_URL=http://host.docker.internal:11434
              (host.docker.internal is mapped to the host gateway by
               the extra_hosts entry in docker-compose.yml)
"""
import json
import logging
from typing import AsyncIterator, List, Optional

import httpx

from app.config import get_settings
from app.schemas.chat import Message

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when Ollama communication fails — safe to surface to the client."""


def _connect_hint(base_url: str) -> str:
    """Return an actionable hint when Ollama is unreachable."""
    if "host.docker.internal" in base_url:
        return (
            f"Cannot connect to Ollama at {base_url}. "
            "Make sure Ollama is running on the VPS host and listening on 0.0.0.0 "
            "(run: OLLAMA_HOST=0.0.0.0 ollama serve)."
        )
    return (
        f"Cannot connect to Ollama at {base_url}. "
        "Make sure Ollama is running: ollama serve"
    )


class OllamaService:
    """Async wrapper around the Ollama HTTP API using httpx."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def base_url(self) -> str:
        return self.settings.ollama_base_url

    @property
    def model(self) -> str:
        return self.settings.ollama_model

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.settings.ollama_timeout, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Health ───────────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """Return Ollama version info or raise OllamaError."""
        try:
            client = await self._get_client()
            response = await client.get("/api/version")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as exc:
            raise OllamaError(_connect_hint(self.base_url)) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama at {self.base_url} timed out. Check that it is running."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise OllamaError(f"Unexpected error checking Ollama health: {exc}") from exc

    async def list_models(self) -> list:
        """Return locally available models."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])
        except httpx.ConnectError as exc:
            raise OllamaError(_connect_hint(self.base_url)) from exc
        except Exception as exc:
            raise OllamaError(f"Failed to list Ollama models: {exc}") from exc

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_ollama_messages(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
    ) -> list:
        result = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        for msg in messages:
            result.append({"role": msg.role.value, "content": msg.content})
        return result

    # ── Non-streaming chat ────────────────────────────────────────────────────

    async def chat(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        target_model = model or self.model
        payload = {
            "model": target_model,
            "messages": self._build_ollama_messages(messages, system_prompt),
            "stream": False,
            "options": {"temperature": 0.7, "top_p": 0.9},
        }

        try:
            client = await self._get_client()
            logger.debug("Non-streaming chat → Ollama model=%s", target_model)
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except httpx.ConnectError as exc:
            raise OllamaError(_connect_hint(self.base_url)) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama request timed out after {self.settings.ollama_timeout}s. "
                "Try increasing OLLAMA_TIMEOUT."
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("Ollama HTTP %s: %s", exc.response.status_code, body)
            if exc.response.status_code == 404:
                raise OllamaError(
                    f"Model '{target_model}' not found on Ollama. "
                    f"Run on the host: ollama pull {target_model}"
                ) from exc
            raise OllamaError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error during Ollama chat")
            raise OllamaError(f"Unexpected Ollama error: {exc}") from exc

    # ── Streaming chat ────────────────────────────────────────────────────────

    async def chat_stream(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        target_model = model or self.model
        payload = {
            "model": target_model,
            "messages": self._build_ollama_messages(messages, system_prompt),
            "stream": True,
            "options": {"temperature": 0.7, "top_p": 0.9},
        }

        try:
            client = await self._get_client()
            logger.debug("Streaming chat → Ollama model=%s", target_model)

            async with client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise OllamaError(
                        f"Model '{target_model}' not found on Ollama. "
                        f"Run on the host: ollama pull {target_model}"
                    )
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON line from Ollama stream: %r", line)
                        continue

                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content

                    if data.get("done", False):
                        return

        except httpx.ConnectError as exc:
            raise OllamaError(_connect_hint(self.base_url)) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama stream timed out after {self.settings.ollama_timeout}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama streaming HTTP %s", exc.response.status_code)
            raise OllamaError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except OllamaError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during Ollama streaming")
            raise OllamaError(f"Unexpected streaming error: {exc}") from exc


# Module-level singleton
_ollama_service: Optional[OllamaService] = None


def get_ollama_service() -> OllamaService:
    global _ollama_service
    if _ollama_service is None:
        _ollama_service = OllamaService()
    return _ollama_service
