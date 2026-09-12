"""Tests for OllamaService behavior."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.chat import Message, MessageRole
from app.services.ollama_service import OllamaError, OllamaService


@pytest.fixture
def service():
    return OllamaService()


def test_build_messages_no_system(service):
    messages = [
        Message(role=MessageRole.user, content="Hi"),
        Message(role=MessageRole.assistant, content="Hello!"),
    ]
    result = service._build_ollama_messages(messages)
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"


def test_build_messages_with_system(service):
    messages = [Message(role=MessageRole.user, content="Hi")]
    result = service._build_ollama_messages(messages, system_prompt="You are helpful.")
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "You are helpful."


@pytest.mark.asyncio
async def test_health_check_connect_error(service):
    import httpx

    with patch.object(service, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_get.return_value = mock_client

        with pytest.raises(OllamaError, match="Cannot connect"):
            await service.health_check()


@pytest.mark.asyncio
async def test_chat_returns_content(service):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={"message": {"content": "I'm doing great!"}}
    )

    with patch.object(service, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get.return_value = mock_client

        messages = [Message(role=MessageRole.user, content="How are you?")]
        result = await service.chat(messages)
        assert result == "I'm doing great!"
