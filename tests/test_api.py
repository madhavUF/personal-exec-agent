"""Basic API tests (no LLM calls)."""
import pytest
from fastapi.testclient import TestClient

# Import app after env is loaded so config paths are correct
from app import app

client = TestClient(app)


def test_docs_available():
    """OpenAPI docs should be served."""
    r = client.get("/docs")
    assert r.status_code == 200


def test_redoc_available():
    """ReDoc should be served."""
    r = client.get("/redoc")
    assert r.status_code == 200


def test_api_status():
    """Status endpoint returns expected keys."""
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "calendar" in data
    assert "gmail" in data
    assert "documents" in data


def test_chat_empty_rejected():
    """Chat with empty query returns 400."""
    r = client.post("/api/chat", json={"query": ""})
    assert r.status_code == 400
    r2 = client.post("/api/chat", json={})
    assert r2.status_code == 422 or r2.status_code == 400


def test_upload_unsupported_type():
    """Upload with unsupported extension returns 400."""
    r = client.post(
        "/api/upload",
        files={"file": ("bad.exe", b"binary", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json().get("error", "")


def test_reindex_returns_json():
    """Reindex endpoint runs and returns JSON (may succeed or fail on empty data)."""
    r = client.post("/api/reindex")
    assert r.status_code in (200, 500)
    data = r.json()
    assert "success" in data or "error" in data
