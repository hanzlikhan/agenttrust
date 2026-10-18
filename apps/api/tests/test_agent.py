"""Tests for the public agent chat endpoints (no API key, IP rate-limited)."""

import pytest

from agenttrust_api.config import settings


def test_chat_requires_groq_key(client):
    """503 when GROQ_API_KEY is not configured."""
    old = settings.GROQ_API_KEY
    settings.GROQ_API_KEY = ""
    try:
        resp = client.post(
            "/api/v1/agent/chat",
            json={"message": "hello", "session_id": "s1"},
        )
    finally:
        settings.GROQ_API_KEY = old
    assert resp.status_code == 503, resp.text
    assert resp.json()["error_code"] == "llm_unavailable"


def test_chat_validation(client):
    """Empty message is a 422, not a Groq call."""
    resp = client.post(
        "/api/v1/agent/chat",
        json={"message": "", "session_id": "s1"},
    )
    assert resp.status_code == 422, resp.text


def test_chat_rate_limited(client, monkeypatch):
    """IP bucket exhaustion returns 429."""
    monkeypatch.setattr(
        "agenttrust_api.routers.agent.check_rate_limit", lambda *a, **k: False
    )
    resp = client.post(
        "/api/v1/agent/chat",
        json={"message": "hello", "session_id": "s1"},
    )
    assert resp.status_code == 429, resp.text


def test_complete_bad_approval_id(client):
    """Malformed approval id is a 422."""
    resp = client.post(
        "/api/v1/agent/complete",
        json={"approval_id": "not-a-uuid"},
    )
    assert resp.status_code == 422, resp.text


def test_complete_unknown_approval(client):
    """Unknown approval id is a 404."""
    import uuid

    resp = client.post(
        "/api/v1/agent/complete",
        json={"approval_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.skip(reason="needs GROQ_API_KEY + seeded demo project; run manually")
def test_chat_full_flow_live():
    """Manual: against a seeded DB with GROQ_API_KEY set, POST a $35 message
    and assert status == 'done'; POST a $150 message and assert
    status == 'awaiting_approval' with an approval_id."""
