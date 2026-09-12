"""
Chat endpoints — both standard and streaming.

POST /api/chat        → full response (waits for complete generation)
POST /api/chat/stream → Server-Sent Events streaming response
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse, Message, MessageRole
from app.services.conversation_service import get_conversation_service
from app.services.ollama_service import OllamaError, get_ollama_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_event(data: dict) -> str:
    """Format a dict as a Server-Sent Event string."""
    return f"data: {json.dumps(data)}\n\n"


def _sse_error(message: str) -> str:
    return _sse_event({"error": message, "done": True})


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message and wait for the complete AI response.
    Suitable for programmatic access; prefer /stream for UI usage.
    """
    conv_service = get_conversation_service()
    ollama_service = get_ollama_service()

    # Resolve or create conversation
    conv_id = conv_service.get_or_create(request.conversation_id)

    # Persist user message
    user_msg = Message(role=MessageRole.user, content=request.message)
    conv_service.add_message(conv_id, user_msg)

    # Fetch conversation history for context
    history = conv_service.get_messages(conv_id)
    system_prompt = request.system_prompt or conv_service.get_system_prompt(conv_id)

    try:
        reply_text = await ollama_service.chat(
            messages=history,
            system_prompt=system_prompt,
            model=request.model,
        )
    except OllamaError as exc:
        logger.error("Ollama error during chat: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    # Persist assistant reply
    assistant_msg = Message(role=MessageRole.assistant, content=reply_text)
    conv_service.add_message(conv_id, assistant_msg)

    model_used = request.model or ollama_service.model

    return ChatResponse(
        message=assistant_msg,
        conversation_id=conv_id,
        model=model_used,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream the AI response via Server-Sent Events.

    Each event is a JSON object:
      { "content": "...", "done": false, "conversation_id": "...", "model": "..." }

    The final event has "done": true and may include "conversation_id".
    On error: { "error": "...", "done": true }
    """
    conv_service = get_conversation_service()
    ollama_service = get_ollama_service()

    # Resolve or create conversation
    conv_id = conv_service.get_or_create(request.conversation_id)

    # Persist user message
    user_msg = Message(role=MessageRole.user, content=request.message)
    conv_service.add_message(conv_id, user_msg)

    # Fetch history and system prompt
    history = conv_service.get_messages(conv_id)
    system_prompt = request.system_prompt or conv_service.get_system_prompt(conv_id)
    model_used = request.model or ollama_service.model

    async def event_generator() -> AsyncIterator[str]:
        full_response: list[str] = []

        # Send conversation_id first so client can associate the stream
        yield _sse_event({
            "content": "",
            "done": False,
            "conversation_id": conv_id,
            "model": model_used,
        })

        try:
            async for chunk in ollama_service.chat_stream(
                messages=history,
                system_prompt=system_prompt,
                model=request.model,
            ):
                full_response.append(chunk)
                yield _sse_event({"content": chunk, "done": False})

        except OllamaError as exc:
            logger.error("Ollama streaming error: %s", exc)
            yield _sse_error(str(exc))
            return
        except Exception as exc:
            logger.exception("Unexpected streaming error")
            yield _sse_error("An unexpected error occurred. Please try again.")
            return

        # Persist the complete assistant reply
        full_text = "".join(full_response)
        if full_text.strip():
            assistant_msg = Message(role=MessageRole.assistant, content=full_text)
            conv_service.add_message(conv_id, assistant_msg)

        # Terminal done event
        yield _sse_event({"content": "", "done": True, "conversation_id": conv_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )
