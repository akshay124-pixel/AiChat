"""
Ollama service layer.

This module is the ONLY place that communicates with Ollama.
Swap this file to change the LLM provider without touching any other code.
"""
import json
import logging
from typing import AsyncIterator, List, Optional

import httpx

from app.config import get_settings
from app.schemas.chat import Message, MessageRole

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when Ollama communication fails."""


class OllamaService:
    """
    Async service that wraps the Ollama HTTP API.

    We use httpx directly for full async streaming support instead of the
    ollama-python SDK which has limited async streaming control.
    """

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

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """Return Ollama version info or raise OllamaError."""
        try:
            client = await self._get_client()
            response = await client.get("/api/version")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}") from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaError(f"Ollama returned HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise OllamaError(f"Unexpected error checking Ollama health: {exc}") from exc

    async def list_models(self) -> list:
        """Return list of locally available Ollama models."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])
        except httpx.ConnectError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}") from exc
        except Exception as exc:
            raise OllamaError(f"Failed to list models: {exc}") from exc

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------

    def _build_ollama_messages(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
    ) -> list:
        """Convert our Message schema list to Ollama chat format."""
        result = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        for msg in messages:
            result.append({"role": msg.role.value, "content": msg.content})
        return result

    # ------------------------------------------------------------------
    # Non-streaming chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """Send messages to Ollama and return the full response text."""
        target_model = model or self.model
        payload = {
            "model": target_model,
            "messages": self._build_ollama_messages(messages, system_prompt),
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            },
        }

        try:
            client = await self._get_client()
            logger.debug("Sending non-streaming chat to Ollama model=%s", target_model)
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except httpx.ConnectError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("Ollama HTTP error %s: %s", exc.response.status_code, body)
            if exc.response.status_code == 404:
                raise OllamaError(
                    f"Model '{target_model}' not found. Run: ollama pull {target_model}"
                ) from exc
            raise OllamaError(f"Ollama returned HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            logger.exception("Unexpected error during Ollama chat")
            raise OllamaError(f"Unexpected error: {exc}") from exc

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Yield text chunks as they stream from Ollama.

        Each yielded value is a string fragment of the assistant reply.
        Raises OllamaError on connection/model problems.
        """
        target_model = model or self.model
        payload = {
            "model": target_model,
            "messages": self._build_ollama_messages(messages, system_prompt),
            "stream": True,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            },
        }

        try:
            client = await self._get_client()
            logger.debug("Starting streaming chat with Ollama model=%s", target_model)

            async with client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise OllamaError(
                        f"Model '{target_model}' not found. Run: ollama pull {target_model}"
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
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama streaming HTTP error %s", exc.response.status_code)
            raise OllamaError(f"Ollama returned HTTP {exc.response.status_code}") from exc
        except OllamaError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during Ollama streaming")
            raise OllamaError(f"Unexpected streaming error: {exc}") from exc


# Module-level singleton — created once, reused across requests
_ollama_service: Optional[OllamaService] = None


def get_ollama_service() -> OllamaService:
    global _ollama_service
    if _ollama_service is None:
        _ollama_service = OllamaService()
    return _ollama_service
