"""Tests for the health endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint_exists(client):
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_structure(client):
    with patch(
        "app.api.health.get_ollama_service"
    ) as mock_factory:
        mock_service = AsyncMock()
        mock_service.health_check = AsyncMock(return_value={"version": "0.4.0"})
        mock_service.list_models = AsyncMock(return_value=[{"name": "qwen3:4b"}])
        mock_factory.return_value = mock_service

        response = client.get("/api/health")
        data = response.json()

    assert "status" in data
    assert "services" in data
    assert "api" in data["services"]
    assert "ollama" in data["services"]


def test_health_degraded_when_ollama_down(client):
    from app.services.ollama_service import OllamaError

    with patch(
        "app.api.health.get_ollama_service"
    ) as mock_factory:
        mock_service = AsyncMock()
        mock_service.health_check = AsyncMock(side_effect=OllamaError("unreachable"))
        mock_factory.return_value = mock_service

        response = client.get("/api/health")
        data = response.json()

    assert response.status_code == 200
    assert data["status"] == "degraded"
    assert data["services"]["ollama"]["status"] == "unavailable"
