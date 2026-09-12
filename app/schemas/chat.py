"""
Pydantic schemas for chat request/response validation.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message content cannot be empty")
        return v


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None  # override default model per-request

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message cannot be empty")
        return v


class ChatResponse(BaseModel):
    message: Message
    conversation_id: str
    model: str


class StreamChunk(BaseModel):
    content: str
    done: bool = False
    conversation_id: Optional[str] = None
    model: Optional[str] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    system_prompt: Optional[str] = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message_preview: Optional[str] = None


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    system_prompt: Optional[str]
    messages: List[Message]


class AddMessageRequest(BaseModel):
    role: MessageRole
    content: str

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Content cannot be empty")
        return v
