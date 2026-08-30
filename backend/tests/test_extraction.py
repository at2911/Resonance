"""Tests for the extraction layer: ExtractionService (validation/retry/
degradation) and the pipeline that maps a validated extraction into real
IncidentState mutations.

No network calls — a FakeLLMExtractionClient stands in for the real
Anthropic client at the exact seam llm_client.LLMExtractionClient defines,
so these tests are deterministic and reproducible without an API key.
"""

from __future__ import annotations

import pytest

from app.models.enums import (
    ActionStatus,
    ClaimStatus,
    ClaimType,
    ParticipantRole,
    RiskSeverity,
    TimelineEventType,
)
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.extraction.llm_client import LLMCallError
from app.services.extraction.pipeline import apply_extraction
from app.services.extraction.schemas import ExtractionContext
from app.services.extraction.service import ExtractionService
from app.services.incident_state.service import IncidentStateService


class FakeLLMExtractionClient:
    """Returns queued responses/exceptions in order; records call count."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def extract(self, context_prompt: str) -> dict:
        self.calls.append(context_prompt)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def service() -> IncidentStateService:
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def incident(service: IncidentStateService):
    return service.create_incident("Payment API outage")


def make_context(incident, speaker_id=None, speaker_name="Alice", text="test utterance"):
    return ExtractionContext(
        incident_title=incident.title,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        utterance_text=text,
    )


def test_fact_extraction_end_to_end(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {
                "claims": [
                    {
                        "type": "FACT",
                        "status": "CONFIRMED",
                        "claim": "Payment API is returning 503 errors",
                        "confidence": 0.97,
                        "evidence": "Speaker reports checking dashboard",
                    }
                ]
            }
        ]
    )
    extraction_service = ExtractionService(fake)
    context = make_context(
        incident, text="Payment API is definitely returning 503s. I checked the dashboard."
    )
    response = extraction_service.extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.type == ClaimType.FACT
    assert claim.status == ClaimStatus.CONFIRMED
    assert claim.text == context.utterance_text


def test_hypothesis_is_not_auto_confirmed(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {
                "claims": [
                    {
                        "type": "HYPOTHESIS",
                        "status": "UNCONFIRMED",
                        "claim": "Database connection pool may be exhausted",
                        "confidence": 0.55,
                    }
                ]
            }
        ]
    )
    context = make_context(incident, text="I think the database connection pool is exhausted.")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert result.claims[0].status == ClaimStatus.UNCONFIRMED


def test_confirmed_without_evidence_is_downgraded_not_dropped(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {
                "claims": [
                    {
                        "type": "FACT",
                        "status": "CONFIRMED",
                        "claim": "Rollback fixed the issue",
                        "confidence": 0.9,
                        "evidence": None,
                    }
                ]
            }
        ]
    )
    context = make_context(incident, text="Rollback fixed it I think")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert len(result.claims) == 1
    assert result.claims[0].status == ClaimStatus.PROBABLE


def test_decision_extraction_creates_decision_timeline_event(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {
                "claims": [
                    {
                        "type": "DECISION",
                        "status": "CONFIRMED",
                        "claim": "Team agreed to roll back the latest deployment",
                        "confidence": 0.95,
                        "evidence": "Explicit team agreement in conversation",
                    }
                ]
            }
        ]
    )
    context = make_context(incident, text="Let's roll back the deployment. Agreed.")
    response = ExtractionService(fake).extract(context)
    apply_extraction(service, incident.id, context, response)

    stored = service.get(incident.id)
    assert any(e.event_type == TimelineEventType.DECISION_RECORDED for e in stored.timeline)


def test_action_extraction_creates_action_with_owner(service, incident):
    fake = FakeLLMExtractionClient(
        [
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
            }
        ]
    )
    context = make_context(incident, text="Bob, check the network metrics.")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert len(result.actions) == 1
    assert result.claims == []
    action = result.actions[0]
    assert action.owner == "Bob"
    assert action.status == ActionStatus.OPEN
    stored = service.get(incident.id)
    assert action.id in stored.actions


def test_risk_extraction_creates_risk(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {
                "claims": [
                    {
                        "type": "RISK",
                        "status": "UNCONFIRMED",
                        "claim": "Rollback may cause data inconsistency",
                        "confidence": 0.6,
                        "severity": "HIGH",
                    }
                ]
            }
        ]
    )
    context = make_context(incident, text="Rolling back could cause data inconsistency.")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert len(result.risks) == 1
    assert result.risks[0].severity == RiskSeverity.HIGH


def test_non_meaningful_utterance_produces_nothing(service, incident):
    fake = FakeLLMExtractionClient([{"claims": []}])
    context = make_context(incident, text="Hey can everyone hear me okay?")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert result.claims == [] and result.actions == [] and result.risks == []
    stored = service.get(incident.id)
    assert len(stored.claims) == 0


def test_invalid_response_is_retried_then_succeeds(service, incident):
    fake = FakeLLMExtractionClient(
        [
            {"claims": [{"type": "NOT_A_TYPE", "status": "CONFIRMED", "claim": "x", "confidence": 0.5}]},
            {
                "claims": [
                    {
                        "type": "FACT",
                        "status": "CONFIRMED",
                        "claim": "Payment API is returning 503 errors",
                        "confidence": 0.9,
                        "evidence": "checked dashboard",
                    }
                ]
            },
        ]
    )
    context = make_context(incident)
    response = ExtractionService(fake).extract(context)

    assert len(fake.calls) == 2
    assert len(response.claims) == 1
    assert response.claims[0].type == ClaimType.FACT


def test_repeated_failure_degrades_gracefully_without_raising(service, incident):
    fake = FakeLLMExtractionClient([LLMCallError("timeout"), LLMCallError("timeout")])
    context = make_context(incident)
    response = ExtractionService(fake).extract(context)

    assert response.claims == []
    stored = service.get(incident.id)
    assert len(stored.claims) == 0


def test_role_hint_updates_only_when_more_confident(service, incident):
    participant = service.add_participant(incident.id, "Alice", ParticipantRole.UNKNOWN, 0.0)
    fake = FakeLLMExtractionClient(
        [
            {
                "speaker_role_hint": "BACKEND_ENGINEER",
                "speaker_role_confidence": 0.7,
                "claims": [],
            }
        ]
    )
    context = make_context(incident, speaker_id=participant.id, speaker_name="Alice")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert result.role_updated is True
    stored = service.get(incident.id)
    assert stored.participants[participant.id].role == ParticipantRole.BACKEND_ENGINEER
    assert stored.participants[participant.id].role_confidence == 0.7


def test_role_hint_never_overwrites_human_correction(service, incident):
    participant = service.add_participant(incident.id, "Alice", ParticipantRole.UNKNOWN, 0.0)
    service.correct_participant_role(incident.id, participant.id, ParticipantRole.INCIDENT_COMMANDER)

    fake = FakeLLMExtractionClient(
        [
            {
                "speaker_role_hint": "SRE",
                "speaker_role_confidence": 0.99,
                "claims": [],
            }
        ]
    )
    context = make_context(incident, speaker_id=participant.id, speaker_name="Alice")
    response = ExtractionService(fake).extract(context)
    result = apply_extraction(service, incident.id, context, response)

    assert result.role_updated is False
    stored = service.get(incident.id)
    assert stored.participants[participant.id].role == ParticipantRole.INCIDENT_COMMANDER
