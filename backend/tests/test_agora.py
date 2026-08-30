"""Tests for the Agora integration: event normalization, speaker mapping,
deduplication, incident association, malformed/error event handling, and
the full HTTP flow (session -> live relay -> webhook history) using mocked
Agora boundaries. These prove the adapter/pipeline logic is correct against
the documented contract (docs/AGORA_INTEGRATION.md) — they are NOT a
substitute for the real Agora smoke test, which requires live credentials
and a real client and has not been run (see that doc's §10).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import ClaimStatus, ClaimType, ParticipantRole
from app.repositories.agora_repository import AgoraRepository
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.agora.adapter import AgoraAdapter
from app.services.agora.identity import resolve_participant
from app.services.agora.pipeline import process_normalized_event
from app.services.agora.rest_client import AgoraRestError
from app.services.agora.schemas import (
    AgentHistoryContent,
    AgentHistoryPayload,
    TranscriptSegmentIngestRequest,
)
from app.services.agora.token import TokenBuildError
from app.services.agora.webhook import WebhookVerificationError, parse_envelope, verify_signature
from app.services.contradiction.service import ContradictionEngine
from app.services.extraction.service import ExtractionService
from app.services.incident_state.service import IncidentStateService

# ---------------------------------------------------------------------
# Fakes at the same boundaries the real clients implement
# ---------------------------------------------------------------------


class FakeExtractionLLMClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def extract(self, prompt):
        return self._responses.pop(0) if self._responses else {"claims": []}


class FakeContradictionLLMClient:
    def assess(self, prompt):
        return {"conflicts": False}


class FakeGapLLMClient:
    def assess(self, prompt):
        from app.models.enums import IncidentDimension

        return {
            "dimensions": [
                {"dimension": d.value, "covered": True, "gap_description": None}
                for d in IncidentDimension
            ]
        }


@pytest.fixture
def state_service():
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def agora_repo():
    return AgoraRepository()


@pytest.fixture
def incident(state_service):
    return state_service.create_incident("Payment API outage")


def extraction_with(responses):
    return ExtractionService(FakeExtractionLLMClient(responses))


NO_CONTRADICTION = ContradictionEngine(FakeContradictionLLMClient())


# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------


def test_normalize_live_segment_produces_spec_shaped_event(incident):
    req = TranscriptSegmentIngestRequest(
        event_id="ev-1", agora_uid="1001", speaker_name="Alice", text="Payment API is down"
    )
    event = AgoraAdapter.normalize_live_segment(incident.id, req, speaker_id="participant-x")
    assert event.event_id == "ev-1"
    assert event.incident_id == incident.id
    assert event.speaker_id == "participant-x"
    assert event.speaker_name == "Alice"
    assert event.text == "Payment API is down"
    assert event.source == "agora"
    assert event.metadata["agora_uid"] == "1001"


def test_normalize_history_entry_is_deterministic_across_reparses(incident):
    payload = AgentHistoryPayload(
        agent_id="agent-1",
        channel="c1",
        contents=[AgentHistoryContent(role="user", content="Payment API is down", speech_start_ms=1000)],
    )
    e1 = AgoraAdapter.normalize_history_entry(incident.id, payload, 0, None, None)
    e2 = AgoraAdapter.normalize_history_entry(incident.id, payload, 0, None, None)
    assert e1.event_id == e2.event_id  # same logical utterance -> same id, enabling dedup


def test_normalize_history_entry_differs_by_content(incident):
    payload = AgentHistoryPayload(
        agent_id="agent-1",
        channel="c1",
        contents=[
            AgentHistoryContent(role="user", content="Payment API is down", speech_start_ms=1000),
            AgentHistoryContent(role="user", content="Database looks fine", speech_start_ms=2000),
        ],
    )
    e1 = AgoraAdapter.normalize_history_entry(incident.id, payload, 0, None, None)
    e2 = AgoraAdapter.normalize_history_entry(incident.id, payload, 1, None, None)
    assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------
# Speaker mapping (identity)
# ---------------------------------------------------------------------


def test_unseen_agora_uid_creates_unknown_role_participant(state_service, incident):
    participant = resolve_participant(state_service, incident.id, "1001", "Alice")
    assert participant.agora_uid == "1001"
    assert participant.role == ParticipantRole.UNKNOWN
    assert participant.role_confidence == 0.0
    assert participant.name == "Alice"


def test_same_agora_uid_resolves_to_same_participant(state_service, incident):
    p1 = resolve_participant(state_service, incident.id, "1001", "Alice")
    p2 = resolve_participant(state_service, incident.id, "1001", "Alice again")
    assert p1.id == p2.id


def test_different_agora_uids_create_different_participants(state_service, incident):
    p1 = resolve_participant(state_service, incident.id, "1001", "Alice")
    p2 = resolve_participant(state_service, incident.id, "1002", "Bob")
    assert p1.id != p2.id


def test_missing_speaker_name_gets_a_placeholder(state_service, incident):
    participant = resolve_participant(state_service, incident.id, "9999", None)
    assert "9999" in participant.name


# ---------------------------------------------------------------------
# Deduplication + incident association (pipeline-level)
# ---------------------------------------------------------------------


def test_duplicate_event_id_is_not_reprocessed(state_service, agora_repo, incident):
    extraction = extraction_with(
        [{"claims": [{"type": "FACT", "status": "CONFIRMED", "claim": "Payment API is down", "confidence": 0.9, "evidence": "checked"}]}]
    )
    req = TranscriptSegmentIngestRequest(event_id="ev-1", agora_uid="1001", text="Payment API is down")
    event = AgoraAdapter.normalize_live_segment(incident.id, req, speaker_id=None)

    first = process_normalized_event(event, agora_repo, state_service, extraction, NO_CONTRADICTION, None, agora_uid="1001")
    second = process_normalized_event(event, agora_repo, state_service, extraction, NO_CONTRADICTION, None, agora_uid="1001")

    assert first.duplicate is False
    assert len(first.claims) == 1
    assert second.duplicate is True
    stored = state_service.get(incident.id)
    assert len(stored.claims) == 1  # not duplicated


def test_agent_speech_is_persisted_but_not_extracted(state_service, agora_repo, incident):
    payload = AgentHistoryPayload(
        agent_id="agent-1",
        channel="c1",
        contents=[AgentHistoryContent(role="assistant", content="Quick incident update...", speech_start_ms=1000)],
    )
    event = AgoraAdapter.normalize_history_entry(incident.id, payload, 0, None, None)
    extraction = extraction_with([])  # would raise IndexError if extraction were attempted

    result = process_normalized_event(event, agora_repo, state_service, extraction, NO_CONTRADICTION, None)

    assert result.skipped_agent_speech is True
    assert agora_repo.has_event(incident.id, event.event_id)
    stored = state_service.get(incident.id)
    assert len(stored.claims) == 0


def test_raw_event_preserved_even_when_extraction_yields_nothing(state_service, agora_repo, incident):
    extraction = extraction_with([{"claims": []}])
    req = TranscriptSegmentIngestRequest(event_id="ev-2", agora_uid="1001", text="hey can you hear me")
    event = AgoraAdapter.normalize_live_segment(incident.id, req, speaker_id=None)

    result = process_normalized_event(event, agora_repo, state_service, extraction, NO_CONTRADICTION, None, agora_uid="1001")

    assert result.claims == []
    assert agora_repo.has_event(incident.id, "ev-2")
    stored_events = agora_repo.list_events(incident.id)
    assert stored_events[0].event.text == "hey can you hear me"


def test_empty_text_segment_is_skipped_without_calling_extraction(state_service, agora_repo, incident):
    class ExplodingExtraction:
        def extract(self, context):
            raise AssertionError("extraction should not be called for empty text")

    req = TranscriptSegmentIngestRequest(event_id="ev-3", agora_uid="1001", text="   ")
    event = AgoraAdapter.normalize_live_segment(incident.id, req, speaker_id=None)
    result = process_normalized_event(
        event, agora_repo, state_service, ExplodingExtraction(), NO_CONTRADICTION, None, agora_uid="1001"
    )
    assert result.claims == []
    assert agora_repo.has_event(incident.id, "ev-3")


# ---------------------------------------------------------------------
# Webhook: signature verification + envelope parsing
# ---------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_signature_valid_v2():
    body = b'{"x":1}'
    sig = _sign("shh", body)
    verify_signature("shh", body, sig, None)  # does not raise


def test_webhook_signature_rejects_bad_secret():
    body = b'{"x":1}'
    sig = _sign("shh", body)
    with pytest.raises(WebhookVerificationError):
        verify_signature("different-secret", body, sig, None)


def test_webhook_signature_rejects_missing_headers():
    with pytest.raises(WebhookVerificationError):
        verify_signature("shh", b"{}", None, None)


def test_webhook_signature_requires_configured_secret():
    with pytest.raises(WebhookVerificationError):
        verify_signature("", b"{}", "whatever", None)


def test_parse_envelope_rejects_malformed_json():
    with pytest.raises(WebhookVerificationError):
        parse_envelope(b"not json at all")


def test_parse_envelope_rejects_missing_required_fields():
    with pytest.raises(WebhookVerificationError):
        parse_envelope(json.dumps({"eventType": 101}).encode())


# ---------------------------------------------------------------------
# Full HTTP flow: session -> live relay -> Slack, with mocked Agora
# boundaries end to end
# ---------------------------------------------------------------------


class FakeAgoraRestClient:
    def __init__(self, agent_id="agent-abc"):
        self.agent_id = agent_id
        self.joined = []
        self.left = []

    def join(self, name, properties):
        self.joined.append({"name": name, "properties": properties})
        return {"agent_id": self.agent_id, "status": "RUNNING"}

    def leave(self, agent_id):
        self.left.append(agent_id)


class FailingAgoraRestClient:
    def join(self, name, properties):
        raise AgoraRestError("simulated Agora outage")

    def leave(self, agent_id):
        raise AgoraRestError("simulated Agora outage")


class FakeTokenBuilder:
    def build_rtc_token(self, channel, uid, ttl_seconds=3600):
        return f"fake-token-{channel}-{uid}"


class FailingTokenBuilder:
    def build_rtc_token(self, channel, uid, ttl_seconds=3600):
        raise TokenBuildError("bad certificate")


from app.api.agora import get_rest_client, get_token_builder  # noqa: E402
from app.api.conversation import get_contradiction_engine, get_extraction_service, get_gap_engine  # noqa: E402
from app.services.agora.dependency import get_agora_repository  # noqa: E402
from app.services.incident_state.dependency import get_incident_state_service  # noqa: E402
from app.services.information_gaps.service import GapEngine  # noqa: E402


@pytest.fixture
def wired_client(state_service, agora_repo):
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    app.dependency_overrides[get_rest_client] = lambda: FakeAgoraRestClient()
    app.dependency_overrides[get_token_builder] = lambda: FakeTokenBuilder()
    app.dependency_overrides[get_extraction_service] = lambda: extraction_with(
        [{"claims": [{"type": "FACT", "status": "CONFIRMED", "claim": "Payment API is down", "confidence": 0.9, "evidence": "checked"}]}]
    )
    app.dependency_overrides[get_contradiction_engine] = lambda: NO_CONTRADICTION
    app.dependency_overrides[get_gap_engine] = lambda: GapEngine(FakeGapLLMClient())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_session_returns_rtc_token_and_persists_association(wired_client, incident):
    r = wired_client.post(f"/incidents/{incident.id}/agora/session", json={"agent_uid": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["incident_id"] == incident.id
    assert body["session"]["status"] == "ACTIVE"
    assert body["session"]["agent_id"] == "agent-abc"
    assert body["rtc_token"].startswith("fake-token-")


def test_create_session_fails_cleanly_when_agora_rest_call_fails(state_service, agora_repo, incident):
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    app.dependency_overrides[get_rest_client] = lambda: FailingAgoraRestClient()
    app.dependency_overrides[get_token_builder] = lambda: FakeTokenBuilder()
    try:
        client = TestClient(app)
        r = client.post(f"/incidents/{incident.id}/agora/session", json={"agent_uid": 1})
        assert r.status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_create_session_fails_cleanly_when_token_build_fails(state_service, agora_repo, incident):
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    app.dependency_overrides[get_rest_client] = lambda: FakeAgoraRestClient()
    app.dependency_overrides[get_token_builder] = lambda: FailingTokenBuilder()
    try:
        client = TestClient(app)
        r = client.post(f"/incidents/{incident.id}/agora/session", json={"agent_uid": 1})
        assert r.status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_live_relay_ingestion_produces_claim_and_timeline_event(wired_client, incident):
    r = wired_client.post(
        f"/incidents/{incident.id}/agora/transcript-events",
        json={"event_id": "ev-1", "agora_uid": "1001", "speaker_name": "Alice", "text": "Payment API is down, I checked"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["claims"]) == 1

    incident_state = wired_client.get(f"/incidents/{incident.id}").json()
    assert any(c["normalized_claim"] == "Payment API is down" for c in incident_state["claims"].values())
    assert any(p["agora_uid"] == "1001" for p in incident_state["participants"].values())


def test_live_relay_duplicate_event_id_is_a_no_op_over_http(wired_client, incident):
    payload = {"event_id": "ev-dup", "agora_uid": "1001", "text": "Payment API is down, I checked"}
    first = wired_client.post(f"/incidents/{incident.id}/agora/transcript-events", json=payload)
    second = wired_client.post(f"/incidents/{incident.id}/agora/transcript-events", json=payload)
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True

    incident_state = wired_client.get(f"/incidents/{incident.id}").json()
    assert len(incident_state["claims"]) == 1


def test_end_session_calls_agora_leave_and_records_timeline_event(wired_client, incident, agora_repo):
    created = wired_client.post(f"/incidents/{incident.id}/agora/session", json={"agent_uid": 1}).json()
    session_id = created["session"]["id"]

    r = wired_client.post(f"/incidents/{incident.id}/agora/session/{session_id}/end")
    assert r.status_code == 200
    assert r.json()["status"] == "ENDED"

    incident_state = wired_client.get(f"/incidents/{incident.id}").json()
    event_types = [e["event_type"] for e in incident_state["timeline"]]
    assert "AGORA_SESSION_STARTED" in event_types
    assert "AGORA_SESSION_ENDED" in event_types


def test_end_session_for_unknown_session_id_returns_404(wired_client, incident):
    r = wired_client.post(f"/incidents/{incident.id}/agora/session/does-not-exist/end")
    assert r.status_code == 404


# ---------------------------------------------------------------------
# Webhook endpoint (signature, malformed body, lifecycle, history, error)
# ---------------------------------------------------------------------


@pytest.fixture
def webhook_client(state_service, agora_repo, monkeypatch):
    from app.api.agora import (
        get_optional_contradiction_engine,
        get_optional_extraction_service,
        get_optional_gap_engine,
    )

    # A fixed instance, not `lambda: extraction_with([...])` — the override
    # is invoked fresh on every request, so recreating the fake client
    # inline would reset its response queue each time instead of letting
    # it progress across the several webhook calls these tests make.
    extraction_service = extraction_with(
        [{"claims": [{"type": "FACT", "status": "CONFIRMED", "claim": "Payment API is down", "confidence": 0.9, "evidence": "checked"}]}] * 5
    )

    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    app.dependency_overrides[get_optional_extraction_service] = lambda: extraction_service
    app.dependency_overrides[get_optional_contradiction_engine] = lambda: NO_CONTRADICTION
    app.dependency_overrides[get_optional_gap_engine] = lambda: GapEngine(FakeGapLLMClient())
    monkeypatch.setenv("AGORA_WEBHOOK_SECRET", "test-secret")
    from app.config import get_settings

    get_settings.cache_clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_webhook_history_with_extraction_unavailable_preserves_raw_events(state_service, agora_repo, monkeypatch, incident):
    """No override for the optional extraction/contradiction/gap getters —
    they fall through to the real ones, which return None without
    LLM_API_KEY configured. The webhook must still succeed (200) and
    preserve the raw transcript rather than erroring or losing it.
    """
    from app.models.enums import AgoraSessionStatus
    from app.services.agora.schemas import AgoraSession

    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    monkeypatch.setenv("AGORA_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("LLM_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    session = AgoraSession(incident_id=incident.id, channel="c1", agent_uid=1, agent_id="agent-1", status=AgoraSessionStatus.ACTIVE)
    agora_repo.save_session(session)

    try:
        client = TestClient(app)
        envelope = {
            "noticeId": "n-unconfigured",
            "productId": 1,
            "eventType": 103,
            "notifyMs": 1,
            "payload": {
                "agent_id": "agent-1",
                "channel": "c1",
                "contents": [{"role": "user", "content": "Payment API is down", "speech_start_ms": 1000}],
            },
        }
        r = _post_webhook(client, envelope)
        assert r.status_code == 200
        assert r.json()["status"] == "extraction_unavailable_raw_events_preserved"

        stored_events = agora_repo.list_events(incident.id)
        assert len(stored_events) == 1
        assert stored_events[0].event.text == "Payment API is down"
        # No claim was created — extraction genuinely did not run — but
        # the raw utterance was not lost.
        assert len(state_service.get(incident.id).claims) == 0
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _post_webhook(client, envelope: dict):
    body = json.dumps(envelope).encode()
    sig = _sign("test-secret", body)
    return client.post("/agora/webhook", content=body, headers={"Agora-Signature-V2": sig, "Content-Type": "application/json"})


def test_webhook_rejects_bad_signature(webhook_client):
    body = json.dumps({"noticeId": "n1", "productId": 1, "eventType": 101, "notifyMs": 1, "payload": {}}).encode()
    r = webhook_client.post("/agora/webhook", content=body, headers={"Agora-Signature-V2": "wrong"})
    assert r.status_code == 401


def test_webhook_rejects_malformed_body(webhook_client):
    body = b"not json"
    sig = _sign("test-secret", body)
    r = webhook_client.post("/agora/webhook", content=body, headers={"Agora-Signature-V2": sig})
    assert r.status_code == 400


def test_webhook_agent_joined_without_known_session_is_ignored_not_errored(webhook_client):
    r = _post_webhook(
        webhook_client,
        {"noticeId": "n1", "productId": 1, "eventType": 101, "notifyMs": 1, "payload": {"agent_id": "unknown-agent", "channel": "c1"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored_unassociated"


def test_webhook_duplicate_notice_id_is_a_no_op(webhook_client):
    envelope = {"noticeId": "n-dup", "productId": 1, "eventType": 104, "notifyMs": 1, "payload": {}}
    r1 = _post_webhook(webhook_client, envelope)
    r2 = _post_webhook(webhook_client, envelope)
    assert r1.json()["status"] == "ignored_event_type"
    assert r2.json()["status"] == "duplicate_ignored"


def test_webhook_lifecycle_and_history_and_error_full_flow(webhook_client, state_service, agora_repo, incident):
    # Simulate a session having been started (association exists) without
    # going through the real /join call.
    from app.models.enums import AgoraSessionStatus
    from app.services.agora.schemas import AgoraSession

    session = AgoraSession(incident_id=incident.id, channel="c1", agent_uid=1, agent_id="agent-1", status=AgoraSessionStatus.ACTIVE)
    agora_repo.save_session(session)

    joined = _post_webhook(
        webhook_client,
        {"noticeId": "n1", "productId": 1, "eventType": 101, "notifyMs": 1, "payload": {"agent_id": "agent-1", "channel": "c1"}},
    )
    assert joined.json()["status"] == "ok"

    history = _post_webhook(
        webhook_client,
        {
            "noticeId": "n2",
            "productId": 1,
            "eventType": 103,
            "notifyMs": 1,
            "payload": {
                "agent_id": "agent-1",
                "channel": "c1",
                "contents": [
                    {"role": "user", "content": "Payment API is down, I checked", "speech_start_ms": 1000},
                    {"role": "assistant", "content": "Understood, looking into it.", "speech_start_ms": 2000},
                ],
            },
        },
    )
    assert history.status_code == 200
    assert history.json()["entries_processed"] == 2

    error = _post_webhook(
        webhook_client,
        {
            "noticeId": "n3",
            "productId": 1,
            "eventType": 110,
            "notifyMs": 1,
            "payload": {"agent_id": "agent-1", "channel": "c1", "errors": [{"module": "asr", "message": "timeout"}]},
        },
    )
    assert error.json()["status"] == "ok"

    left = _post_webhook(
        webhook_client,
        {"noticeId": "n4", "productId": 1, "eventType": 102, "notifyMs": 1, "payload": {"agent_id": "agent-1", "channel": "c1", "status": "left"}},
    )
    assert left.json()["status"] == "ok"

    incident_state = state_service.get(incident.id)
    event_types = [e.event_type.value for e in incident_state.timeline]
    assert "AGORA_AGENT_JOINED" in event_types
    assert "AGORA_AGENT_ERROR" in event_types
    assert "AGORA_AGENT_LEFT" in event_types
    # The user line produced a fact; the assistant line did not.
    assert any(c.type == ClaimType.FACT and c.status == ClaimStatus.CONFIRMED for c in incident_state.claims.values())
    assert len(incident_state.claims) == 1


def test_webhook_history_redelivery_does_not_duplicate_claims(webhook_client, state_service, agora_repo, incident):
    from app.models.enums import AgoraSessionStatus
    from app.services.agora.schemas import AgoraSession

    session = AgoraSession(incident_id=incident.id, channel="c1", agent_uid=1, agent_id="agent-1", status=AgoraSessionStatus.ACTIVE)
    agora_repo.save_session(session)

    envelope = {
        "noticeId": "n-hist-1",
        "productId": 1,
        "eventType": 103,
        "notifyMs": 1,
        "payload": {
            "agent_id": "agent-1",
            "channel": "c1",
            "contents": [{"role": "user", "content": "Payment API is down, I checked", "speech_start_ms": 1000}],
        },
    }
    first = _post_webhook(webhook_client, envelope)
    assert first.json()["entries_processed"] == 1

    # Same noticeId redelivered (Agora's documented at-least-once delivery).
    second = _post_webhook(webhook_client, envelope)
    assert second.json()["status"] == "duplicate_ignored"

    incident_state = state_service.get(incident.id)
    assert len(incident_state.claims) == 1


# ---------------------------------------------------------------------
# Full chain: Agora live relay -> conflict detection -> action -> gap
# engine -> existing Slack approval flow, all still working end to end
# with Agora-shaped input instead of manually-posted utterances.
# ---------------------------------------------------------------------


def test_full_chain_agora_to_slack_with_mocked_boundaries(state_service, agora_repo, monkeypatch):
    """Mirrors the spec's own demo scenario (DB vs network hypothesis
    conflict, action assignment, Slack proposal + approval), but driven
    entirely through the Agora live-relay endpoint instead of
    POST /utterances — proving Agora is genuinely just another utterance
    source into the unmodified reasoning pipeline, and that every
    downstream system (conflict engine, gap engine, approval gate, Slack)
    still works unchanged.
    """
    from app.api.slack import get_slack_client

    incident = state_service.create_incident("Payment API outage")

    extraction_responses = [
        {
            "claims": [
                {
                    "type": "FACT",
                    "status": "CONFIRMED",
                    "claim": "Payment API is returning 503 errors",
                    "confidence": 0.95,
                    "evidence": "Engineer checked the dashboard",
                    "entities": ["payment-api"],
                }
            ]
        },
        {
            "claims": [
                {
                    "type": "HYPOTHESIS",
                    "status": "UNCONFIRMED",
                    "claim": "Database connection pool may be exhausted",
                    "confidence": 0.55,
                    "entities": ["database"],
                }
            ]
        },
        {
            "claims": [
                {
                    "type": "HYPOTHESIS",
                    "status": "UNCONFIRMED",
                    "claim": "Database appears healthy; network is dropping packets",
                    "confidence": 0.6,
                    "entities": ["database", "network"],
                }
            ]
        },
        {
            "claims": [
                {
                    "type": "ACTION",
                    "status": "UNCONFIRMED",
                    "claim": "Check network metrics",
                    "confidence": 0.9,
                    "action_owner": "Bob",
                }
            ]
        },
    ]

    class SequencedExtractionClient:
        def __init__(self, responses):
            self._responses = list(responses)

        def extract(self, prompt):
            return self._responses.pop(0) if self._responses else {"claims": []}

    class ConflictOnDbHealthClient:
        def assess(self, prompt):
            if "Database" in prompt or "database" in prompt:
                return {
                    "conflicts": True,
                    "conflict_type": "DATABASE_HEALTH",
                    "explanation": "Both claims about database health cannot be true simultaneously",
                }
            return {"conflicts": False}

    # Dependency overrides are re-invoked on every request, so the stateful
    # fakes (the response queue in particular) must be constructed once
    # and captured by reference — a `lambda: ExtractionService(Seq(...))`
    # would rebuild the queue fresh on each call and never progress past
    # the first response.
    extraction_service = ExtractionService(SequencedExtractionClient(extraction_responses))
    contradiction_engine = ContradictionEngine(ConflictOnDbHealthClient())
    gap_engine = GapEngine(FakeGapLLMClient())
    fake_slack = FakeSlackClientForE2E()

    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_agora_repository] = lambda: agora_repo
    app.dependency_overrides[get_rest_client] = lambda: FakeAgoraRestClient()
    app.dependency_overrides[get_token_builder] = lambda: FakeTokenBuilder()
    app.dependency_overrides[get_extraction_service] = lambda: extraction_service
    app.dependency_overrides[get_contradiction_engine] = lambda: contradiction_engine
    app.dependency_overrides[get_gap_engine] = lambda: gap_engine
    app.dependency_overrides[get_slack_client] = lambda: fake_slack
    monkeypatch.setenv("SLACK_CHANNEL_ID", "#payments-incident")
    from app.config import get_settings

    get_settings.cache_clear()

    try:
        client = TestClient(app)

        session = client.post(f"/incidents/{incident.id}/agora/session", json={"agent_uid": 1}).json()
        assert session["session"]["status"] == "ACTIVE"

        utterances = [
            ("1001", "Alice", "Payment API is returning 503s, I checked the dashboard"),
            ("1001", "Alice", "I think the database connection pool is exhausted"),
            ("1002", "Bob", "The database looks healthy, the network is dropping packets"),
            ("1002", "Bob", "Bob, check the network metrics"),
        ]
        results = []
        for i, (uid, name, text) in enumerate(utterances):
            r = client.post(
                f"/incidents/{incident.id}/agora/transcript-events",
                json={"event_id": f"ev-{i}", "agora_uid": uid, "speaker_name": name, "text": text},
            )
            assert r.status_code == 200
            results.append(r.json())

        # Conflict detected purely from Agora-relayed speech.
        assert len(results[2]["conflicts"]) == 1
        assert results[2]["conflicts"][0]["conflict_type"] == "DATABASE_HEALTH"

        # Action assigned with real ownership.
        assert len(results[3]["actions"]) == 1
        assert results[3]["actions"][0]["owner"] == "Bob"

        incident_state = client.get(f"/incidents/{incident.id}").json()
        assert len(incident_state["claims"]) == 3
        assert len(incident_state["conflicts"]) == 1
        assert len(incident_state["actions"]) == 1
        # Two distinct real participants resolved from two distinct agora uids.
        assert len(incident_state["participants"]) == 2

        # Existing Slack proposal/approval/execution flow, unmodified.
        proposal = client.post(f"/incidents/{incident.id}/slack-updates").json()
        assert proposal["approval_status"] == "PENDING"
        assert "Payment API is returning 503 errors" in proposal["payload"]["text"]

        pre_approval_execute = client.post(
            f"/incidents/{incident.id}/external-actions/{proposal['id']}/execute"
        )
        assert pre_approval_execute.status_code == 409  # approval gate still enforced

        client.post(
            f"/incidents/{incident.id}/external-actions/{proposal['id']}/decision",
            json={"approved": True, "approved_by": "ic-alice"},
        )
        executed = client.post(f"/incidents/{incident.id}/external-actions/{proposal['id']}/execute")
        assert executed.status_code == 200
        assert executed.json()["execution_status"] == "SUCCEEDED"
        assert len(fake_slack.calls) == 1

        summary = client.get(f"/incidents/{incident.id}/summary").json()
        assert summary["root_cause_confirmed"] is False
        assert summary["root_cause_statement"] == "Root cause remains unconfirmed."
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


class FakeSlackClientForE2E:
    def __init__(self):
        self.calls = []

    def post_message(self, channel, text):
        self.calls.append({"channel": channel, "text": text})
        return {"ts": "111.11", "channel": channel}
