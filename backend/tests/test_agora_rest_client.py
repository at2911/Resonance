"""Tests for HttpxAgoraConversationalAIClient itself — previously only
verified by hand against the real Agora API (see docs/AGORA_INTEGRATION.md),
never unit-tested. Added after a real live session hit exactly the
TaskNotFound-on-/leave case these tests pin down: an agent that already
timed out on Agora's side must not permanently strand our own session in
ACTIVE.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.agora.rest_client import AgoraRestError, HttpxAgoraConversationalAIClient


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        import json

        return json.loads(self.text)


@pytest.fixture
def client():
    return HttpxAgoraConversationalAIClient("app-id", "key", "secret", "https://api.agora.io/api/conversational-ai-agent/v2")


def test_leave_treats_real_task_not_found_404_as_success_not_a_raise(client, monkeypatch):
    """The exact real response this session observed: the agent had
    already timed out on Agora's side by the time End Session was clicked."""
    body = '{"detail":"The session was not found, has already ended, or failed to start.","reason":"TaskNotFound"}'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(404, body))

    client.leave("some-agent-id")  # must not raise


def test_leave_still_raises_on_a_genuine_error(client, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(500, '{"detail":"internal error"}'))

    with pytest.raises(AgoraRestError):
        client.leave("some-agent-id")


def test_leave_still_raises_on_a_genuine_401(client, monkeypatch):
    """A 404 is specifically "already gone" (success); other 4xx codes -
    like bad credentials - are real failures and must still surface."""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(401, '{"detail":"unauthorized"}'))

    with pytest.raises(AgoraRestError):
        client.leave("some-agent-id")


def test_join_still_raises_on_404_unlike_leave(client, monkeypatch):
    """The 404-is-success carve-out is deliberately narrow, scoped to
    leave() only - /join returning 404 is a real routing/config problem,
    not "already done"."""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(404, '{"detail":"not found"}'))

    with pytest.raises(AgoraRestError):
        client.join("agent-name", {"channel": "c1"})


def test_speak_still_raises_on_404_unlike_leave(client, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(404, '{"reason":"TaskNotFound"}'))

    with pytest.raises(AgoraRestError):
        client.speak("some-agent-id", "hello")
