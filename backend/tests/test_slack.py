"""Tests for the Slack integration: the deterministic message composer, the
SlackWebClient error-mapping boundary, and the full propose -> approve ->
execute HTTP flow, including the failure-then-retry path and the
"never claim success" / "never execute without approval" guarantees.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import (
    ActionStatus,
    ClaimStatus,
    ClaimType,
    ExternalActionType,
    GapImportance,
)
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.incident_state.dependency import get_incident_state_service
from app.services.incident_state.service import IncidentStateService
from app.services.slack.client import SlackCallError, SlackWebClient
from app.services.slack.composer import SlackMessageComposer
from app.api.slack import get_slack_client


@pytest.fixture
def service() -> IncidentStateService:
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def incident(service: IncidentStateService):
    return service.create_incident("Payment API outage")


# ---------------------------------------------------------------------
# Composer (pure, deterministic — no client/network involved)
# ---------------------------------------------------------------------


def test_composer_includes_confirmed_facts_and_unconfirmed_root_cause(service, incident):
    service.add_claim(
        incident.id,
        text="x",
        normalized_claim="payment API is returning 503 errors",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.9,
        evidence="checked dashboard",
    )
    service.add_claim(
        incident.id,
        text="x",
        normalized_claim="database connection pool may be exhausted",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.5,
    )
    stored = service.get(incident.id)
    text = SlackMessageComposer.compose(stored)

    assert "Payment API is returning 503 errors." in text
    assert "remains unconfirmed" in text
    assert "Database connection pool may be exhausted" in text


def test_composer_reports_no_open_actions(service, incident):
    stored = service.get(incident.id)
    text = SlackMessageComposer.compose(stored)
    assert "No investigation actions are currently open." in text


def test_composer_reports_open_action_count(service, incident):
    service.add_action(incident.id, "Check network metrics", owner="bob")
    stored = service.get(incident.id)
    text = SlackMessageComposer.compose(stored)
    assert "Investigation is ongoing (1 open action(s))." in text


def test_composer_includes_critical_gaps(service, incident):
    service.add_information_gap(incident.id, "Customer impact unknown", GapImportance.CRITICAL)
    stored = service.get(incident.id)
    text = SlackMessageComposer.compose(stored)
    assert "Open critical gaps: Customer impact unknown." in text


def test_composer_states_confirmed_root_cause(service, incident):
    service.add_claim(
        incident.id,
        text="x",
        normalized_claim="root cause confirmed as database connection pool exhaustion",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.95,
        evidence="Team confirmed via pool metrics",
    )
    stored = service.get(incident.id)
    text = SlackMessageComposer.compose(stored)
    assert "remains unconfirmed" not in text
    assert "root cause" in text.lower()


# ---------------------------------------------------------------------
# SlackWebClient boundary (error mapping — no real network call)
# ---------------------------------------------------------------------


def test_slack_web_client_requires_bot_token():
    with pytest.raises(SlackCallError):
        SlackWebClient("")


def test_slack_web_client_maps_api_error(monkeypatch):
    from slack_sdk.errors import SlackApiError

    client = SlackWebClient("xoxb-fake-token")

    def raise_error(**kwargs):
        raise SlackApiError("boom", response={"error": "channel_not_found"})

    monkeypatch.setattr(client._client, "chat_postMessage", raise_error)
    with pytest.raises(SlackCallError):
        client.post_message(channel="#nope", text="hi")


def test_slack_web_client_maps_not_ok_response(monkeypatch):
    client = SlackWebClient("xoxb-fake-token")
    monkeypatch.setattr(client._client, "chat_postMessage", lambda **kw: {"ok": False, "error": "rate_limited"})
    with pytest.raises(SlackCallError):
        client.post_message(channel="#c", text="hi")


def test_slack_web_client_returns_ts_and_channel_on_success(monkeypatch):
    client = SlackWebClient("xoxb-fake-token")
    monkeypatch.setattr(
        client._client, "chat_postMessage", lambda **kw: {"ok": True, "ts": "123.45", "channel": "#c"}
    )
    result = client.post_message(channel="#c", text="hi")
    assert result == {"ts": "123.45", "channel": "#c"}


# ---------------------------------------------------------------------
# Full HTTP flow: propose -> approve -> execute (fake Slack client)
# ---------------------------------------------------------------------


class FakeSlackClient:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.calls: list[dict] = []

    def post_message(self, channel: str, text: str) -> dict:
        self.calls.append({"channel": channel, "text": text})
        if self.should_fail:
            raise SlackCallError("simulated network failure")
        return {"ts": "999.99", "channel": channel}


@pytest.fixture
def client_and_service(monkeypatch):
    state_service = IncidentStateService(InMemoryIncidentRepository())
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    monkeypatch.setenv("SLACK_CHANNEL_ID", "#payments-incident")
    from app.config import get_settings

    get_settings.cache_clear()
    yield TestClient(app), state_service
    app.dependency_overrides.pop(get_incident_state_service, None)
    app.dependency_overrides.pop(get_slack_client, None)
    get_settings.cache_clear()


def test_propose_composes_message_from_state(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    state_service.add_claim(
        incident.id,
        text="x",
        normalized_claim="payment API is returning 503 errors",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.9,
        evidence="checked dashboard",
    )

    r = client.post(f"/incidents/{incident.id}/slack-updates")
    assert r.status_code == 200
    body = r.json()
    assert body["action_type"] == "SLACK_MESSAGE"
    assert body["approval_status"] == "PENDING"
    assert "Payment API is returning 503 errors" in body["payload"]["text"]
    assert body["payload"]["channel"] == "#payments-incident"


def test_execute_without_approval_is_rejected(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    app.dependency_overrides[get_slack_client] = lambda: FakeSlackClient()

    proposed = client.post(f"/incidents/{incident.id}/slack-updates").json()
    r = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    assert r.status_code == 409


def test_approve_then_execute_posts_to_slack(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    fake_slack = FakeSlackClient()
    app.dependency_overrides[get_slack_client] = lambda: fake_slack

    proposed = client.post(f"/incidents/{incident.id}/slack-updates").json()
    approved = client.post(
        f"/incidents/{incident.id}/external-actions/{proposed['id']}/decision",
        json={"approved": True, "approved_by": "ic-alice"},
    )
    assert approved.json()["approval_status"] == "APPROVED"

    executed = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["execution_status"] == "SUCCEEDED"
    assert "ts=999.99" in body["execution_result"]
    assert len(fake_slack.calls) == 1


def test_failed_execution_is_recorded_not_faked_and_can_be_retried(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    failing_slack = FakeSlackClient(should_fail=True)
    app.dependency_overrides[get_slack_client] = lambda: failing_slack

    proposed = client.post(f"/incidents/{incident.id}/slack-updates").json()
    client.post(
        f"/incidents/{incident.id}/external-actions/{proposed['id']}/decision",
        json={"approved": True, "approved_by": "ic-alice"},
    )

    failed = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    assert failed.status_code == 200
    assert failed.json()["execution_status"] == "FAILED"
    assert "simulated network failure" in failed.json()["execution_result"]

    # Retry with a working client — must succeed without needing re-approval.
    working_slack = FakeSlackClient()
    app.dependency_overrides[get_slack_client] = lambda: working_slack
    retried = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    assert retried.status_code == 200
    assert retried.json()["execution_status"] == "SUCCEEDED"


def test_cannot_double_execute_after_success(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    fake_slack = FakeSlackClient()
    app.dependency_overrides[get_slack_client] = lambda: fake_slack

    proposed = client.post(f"/incidents/{incident.id}/slack-updates").json()
    client.post(
        f"/incidents/{incident.id}/external-actions/{proposed['id']}/decision",
        json={"approved": True, "approved_by": "ic-alice"},
    )
    client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    second = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")

    assert second.status_code == 409
    assert len(fake_slack.calls) == 1


def test_rejected_proposal_cannot_be_executed(client_and_service):
    client, state_service = client_and_service
    incident = state_service.create_incident("Payment API outage")
    app.dependency_overrides[get_slack_client] = lambda: FakeSlackClient()

    proposed = client.post(f"/incidents/{incident.id}/slack-updates").json()
    client.post(
        f"/incidents/{incident.id}/external-actions/{proposed['id']}/decision",
        json={"approved": False, "approved_by": "ic-alice"},
    )
    r = client.post(f"/incidents/{incident.id}/external-actions/{proposed['id']}/execute")
    assert r.status_code == 409


def test_propose_without_channel_configured_returns_503(monkeypatch):
    state_service = IncidentStateService(InMemoryIncidentRepository())
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    monkeypatch.setenv("SLACK_CHANNEL_ID", "")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        incident = state_service.create_incident("Payment API outage")
        client = TestClient(app)
        r = client.post(f"/incidents/{incident.id}/slack-updates")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.pop(get_incident_state_service, None)
        get_settings.cache_clear()
