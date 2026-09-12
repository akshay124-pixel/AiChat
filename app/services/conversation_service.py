"""
In-memory conversation store.

This service manages all conversation state.
Replace the storage backend here (PostgreSQL, Redis, etc.) without
touching the API layer.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from app.config import get_settings
from app.schemas.chat import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    Message,
    MessageRole,
)

logger = logging.getLogger(__name__)


class ConversationNotFoundError(Exception):
    pass


class ConversationLimitError(Exception):
    pass


class _ConversationRecord:
    """Internal data structure for a single conversation."""

    def __init__(self, title: str, system_prompt: Optional[str] = None) -> None:
        self.id: str = str(uuid4())
        self.title: str = title
        self.system_prompt: Optional[str] = system_prompt
        self.messages: List[Message] = []
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = datetime.now(timezone.utc)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_summary(self) -> ConversationSummary:
        last_preview: Optional[str] = None
        if self.messages:
            raw = self.messages[-1].content
            last_preview = raw[:120] + ("…" if len(raw) > 120 else "")
        return ConversationSummary(
            id=self.id,
            title=self.title,
            created_at=self.created_at,
            updated_at=self.updated_at,
            message_count=len(self.messages),
            last_message_preview=last_preview,
        )

    def to_detail(self) -> ConversationDetail:
        return ConversationDetail(
            id=self.id,
            title=self.title,
            created_at=self.created_at,
            updated_at=self.updated_at,
            system_prompt=self.system_prompt,
            messages=list(self.messages),
        )


class ConversationService:
    """Thread-safe (single-process) in-memory conversation manager."""

    def __init__(self) -> None:
        self._store: Dict[str, _ConversationRecord] = {}
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_conversation(self, payload: ConversationCreate) -> ConversationDetail:
        if len(self._store) >= self._settings.max_conversations:
            # Evict the oldest conversation to make room
            oldest_id = min(self._store, key=lambda k: self._store[k].created_at)
            del self._store[oldest_id]
            logger.warning("Evicted oldest conversation %s to stay within limit", oldest_id)

        title = payload.title or "New Conversation"
        record = _ConversationRecord(title=title, system_prompt=payload.system_prompt)
        self._store[record.id] = record
        logger.info("Created conversation %s", record.id)
        return record.to_detail()

    def get_conversation(self, conversation_id: str) -> ConversationDetail:
        record = self._store.get(conversation_id)
        if not record:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return record.to_detail()

    def list_conversations(self) -> List[ConversationSummary]:
        """Return all conversations sorted by most recently updated."""
        records = sorted(self._store.values(), key=lambda r: r.updated_at, reverse=True)
        return [r.to_summary() for r in records]

    def delete_conversation(self, conversation_id: str) -> None:
        if conversation_id not in self._store:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        del self._store[conversation_id]
        logger.info("Deleted conversation %s", conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> ConversationDetail:
        record = self._store.get(conversation_id)
        if not record:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        record.title = title.strip() or "Untitled"
        record.touch()
        return record.to_detail()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(self, conversation_id: str, message: Message) -> Message:
        record = self._store.get(conversation_id)
        if not record:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        if len(record.messages) >= self._settings.max_messages_per_conversation:
            # Drop the oldest non-system message pair
            record.messages = record.messages[2:]

        record.messages.append(message)
        record.touch()

        # Auto-title from first user message
        if len(record.messages) == 1 and message.role == MessageRole.user:
            raw = message.content.strip()
            record.title = raw[:60] + ("…" if len(raw) > 60 else "")

        return message

    def get_messages(self, conversation_id: str) -> List[Message]:
        record = self._store.get(conversation_id)
        if not record:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return list(record.messages)

    def get_system_prompt(self, conversation_id: str) -> Optional[str]:
        record = self._store.get(conversation_id)
        if not record:
            return None
        return record.system_prompt

    def get_or_create(self, conversation_id: Optional[str]) -> str:
        """Return existing conversation ID or create a new one."""
        if conversation_id and conversation_id in self._store:
            return conversation_id
        detail = self.create_conversation(ConversationCreate())
        return detail.id


# Module-level singleton
_conversation_service: Optional[ConversationService] = None


def get_conversation_service() -> ConversationService:
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService()
    return _conversation_service
