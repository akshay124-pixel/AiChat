"""Conversation management endpoints."""
import logging
from typing import List

from fastapi import APIRouter, HTTPException

from app.schemas.chat import (
    AddMessageRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    Message,
)
from app.services.conversation_service import (
    ConversationNotFoundError,
    get_conversation_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found")


@router.get("", response_model=List[ConversationSummary])
async def list_conversations():
    """Return all conversations sorted by most recently updated."""
    service = get_conversation_service()
    return service.list_conversations()


@router.post("", response_model=ConversationDetail, status_code=201)
async def create_conversation(payload: ConversationCreate):
    """Create a new conversation."""
    service = get_conversation_service()
    return service.create_conversation(payload)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str):
    """Return a conversation with its full message history."""
    service = get_conversation_service()
    try:
        return service.get_conversation(conversation_id)
    except ConversationNotFoundError:
        raise _not_found(conversation_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    service = get_conversation_service()
    try:
        service.delete_conversation(conversation_id)
    except ConversationNotFoundError:
        raise _not_found(conversation_id)


@router.patch("/{conversation_id}/title", response_model=ConversationDetail)
async def rename_conversation(conversation_id: str, body: dict):
    """Rename a conversation."""
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    service = get_conversation_service()
    try:
        return service.rename_conversation(conversation_id, title)
    except ConversationNotFoundError:
        raise _not_found(conversation_id)


@router.post("/{conversation_id}/messages", response_model=Message, status_code=201)
async def add_message(conversation_id: str, payload: AddMessageRequest):
    """Manually append a message to a conversation."""
    service = get_conversation_service()
    try:
        message = Message(role=payload.role, content=payload.content)
        return service.add_message(conversation_id, message)
    except ConversationNotFoundError:
        raise _not_found(conversation_id)
