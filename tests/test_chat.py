"""Tests for chat endpoints and schema validation."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.schemas.chat import ChatRequest


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_chat_request_empty_message_raises():
    with pytest.raises(Exception):
        ChatRequest(message="   ")


def test_chat_request_valid():
    req = ChatRequest(message="Hello")
    assert req.message == "Hello"


def test_chat_request_optional_fields():
    req = ChatRequest(message="Hi", conversation_id="abc", model="qwen3:4b")
    assert req.conversation_id == "abc"
    assert req.model == "qwen3:4b"


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

def test_chat_endpoint_success(client):
    with patch("app.api.chat.get_ollama_service") as mock_factory:
        mock_service = AsyncMock()
        mock_service.model = "qwen3:4b"
        mock_service.chat = AsyncMock(return_value="Hello! How can I help?")
        mock_factory.return_value = mock_service

        response = client.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"]["role"] == "assistant"
    assert "conversation_id" in data


def test_chat_endpoint_empty_message(client):
    response = client.post("/api/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_endpoint_ollama_unavailable(client):
    from app.services.ollama_service import OllamaError

    with patch("app.api.chat.get_ollama_service") as mock_factory:
        mock_service = AsyncMock()
        mock_service.model = "qwen3:4b"
        mock_service.chat = AsyncMock(side_effect=OllamaError("unreachable"))
        mock_factory.return_value = mock_service

        response = client.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Conversations endpoint
# ---------------------------------------------------------------------------

def test_create_and_list_conversation(client):
    create_resp = client.post("/api/conversations", json={"title": "Test Chat"})
    assert create_resp.status_code == 201
    conv = create_resp.json()
    assert conv["title"] == "Test Chat"

    list_resp = client.get("/api/conversations")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert conv["id"] in ids


def test_delete_conversation(client):
    create_resp = client.post("/api/conversations", json={})
    conv_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/conversations/{conv_id}")
    assert del_resp.status_code == 204

    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.status_code == 404


def test_delete_nonexistent_conversation(client):
    response = client.delete("/api/conversations/does-not-exist")
    assert response.status_code == 404
