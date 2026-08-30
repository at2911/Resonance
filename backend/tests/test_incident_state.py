"""Tests for the Incident State Engine — the P0 foundation everything else
builds on. These tests intentionally exercise the epistemic-safety and
human-in-the-loop rules described in the project spec, not just happy paths.
"""

import pytest

from app.models.enums import (
    ActionPriority,
    ActionStatus,
    ClaimStatus,
    ClaimType,
    ConflictType,
    ExternalActionType,
    GapImportance,
    ParticipantRole,
    RiskSeverity,
)
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.incident_state.service import (
    EvidenceRequiredError,
    IncidentStateService,
    InvalidStateTransitionError,
)


@pytest.fixture
def service() -> IncidentStateService:
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def incident(service: IncidentStateService):
    return service.create_incident("Payment API outage")


def test_create_incident_emits_detected_event(service, incident):
    assert incident.clarity_score == 100
    assert len(incident.timeline) == 1
    assert incident.timeline[0].event_type.value == "INCIDENT_DETECTED"


def test_add_participant_role_recognition(service, incident):
    p = service.add_participant(incident.id, "Alice", ParticipantRole.BACKEND_ENGINEER, 0.8)
    stored = service.get(incident.id)
    assert stored.participants[p.id].role == ParticipantRole.BACKEND_ENGINEER
    assert stored.participants[p.id].role_confidence == 0.8


def test_add_fact_claim(service, incident):
    claim = service.add_claim(
        incident.id,
        text="I checked the payment dashboard and the API is returning 503.",
        normalized_claim="Payment API is returning 503 errors",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.97,
        speaker_id="alice",
        evidence="Speaker reports checking dashboard",
    )
    assert claim.status == ClaimStatus.CONFIRMED
    stored = service.get(incident.id)
    assert claim.id in stored.claims


def test_hypothesis_cannot_be_created_as_confirmed_without_evidence(service, incident):
    with pytest.raises(EvidenceRequiredError):
        service.add_claim(
            incident.id,
            text="I think the DB pool is exhausted.",
            normalized_claim="Database connection pool may be exhausted",
            type=ClaimType.HYPOTHESIS,
            status=ClaimStatus.CONFIRMED,
            confidence=0.55,
        )


def test_repeating_a_hypothesis_never_auto_confirms_it(service, incident):
    """Core epistemic-safety rule: a second mention must not silently
    upgrade a hypothesis to CONFIRMED without new evidence.
    """
    claim = service.add_claim(
        incident.id,
        text="I think the DB pool is exhausted.",
        normalized_claim="Database connection pool may be exhausted",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.55,
        speaker_id="alice",
    )
    with pytest.raises(EvidenceRequiredError):
        service.update_claim_status(incident.id, claim.id, ClaimStatus.CONFIRMED)

    updated = service.update_claim_status(
        incident.id, claim.id, ClaimStatus.CONFIRMED, evidence="Bob confirmed via pool metrics dashboard"
    )
    assert updated.status == ClaimStatus.CONFIRMED


def test_action_assignment_and_lifecycle(service, incident):
    action = service.add_action(incident.id, "Check network metrics", owner="bob")
    assert action.status == ActionStatus.OPEN

    in_progress = service.update_action_status(incident.id, action.id, ActionStatus.IN_PROGRESS)
    assert in_progress.status == ActionStatus.IN_PROGRESS

    with pytest.raises(EvidenceRequiredError):
        service.update_action_status(incident.id, action.id, ActionStatus.COMPLETED)

    completed = service.update_action_status(
        incident.id, action.id, ActionStatus.COMPLETED, completion_evidence="Packet loss normal"
    )
    assert completed.status == ActionStatus.COMPLETED
    assert completed.completion_evidence == "Packet loss normal"


def test_completed_action_cannot_transition_further(service, incident):
    action = service.add_action(incident.id, "Check network metrics", owner="bob")
    service.update_action_status(
        incident.id, action.id, ActionStatus.COMPLETED, completion_evidence="done"
    )
    with pytest.raises(InvalidStateTransitionError):
        service.update_action_status(incident.id, action.id, ActionStatus.OPEN)


def test_conflict_detection_preserves_both_claims_and_marks_disputed(service, incident):
    claim_a = service.add_claim(
        incident.id,
        text="The database is timing out.",
        normalized_claim="Database instability",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.5,
        speaker_id="alice",
    )
    claim_b = service.add_claim(
        incident.id,
        text="The database looks healthy; the network is dropping packets.",
        normalized_claim="Database appears healthy",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.5,
        speaker_id="bob",
    )
    conflict = service.add_conflict(
        incident.id,
        claim_a.id,
        claim_b.id,
        ConflictType.DATABASE_HEALTH,
        "Alice reports DB instability while Bob reports the DB is healthy",
    )
    stored = service.get(incident.id)
    assert claim_a.id in stored.claims and claim_b.id in stored.claims
    assert stored.claims[claim_a.id].status == ClaimStatus.DISPUTED
    assert stored.claims[claim_b.id].status == ClaimStatus.DISPUTED
    assert stored.conflicts[conflict.id].status.value == "OPEN"


def test_conflict_requires_evidence_to_resolve(service, incident):
    claim_a = service.add_claim(
        incident.id, "a", "Database instability", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, 0.5
    )
    claim_b = service.add_claim(
        incident.id, "b", "Database appears healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, 0.5
    )
    conflict = service.add_conflict(
        incident.id, claim_a.id, claim_b.id, ConflictType.DATABASE_HEALTH, "explanation"
    )
    with pytest.raises(EvidenceRequiredError):
        service.resolve_conflict(incident.id, conflict.id, resolution_evidence="")

    resolved = service.resolve_conflict(
        incident.id, conflict.id, resolution_evidence="Confirmed via DB metrics dashboard"
    )
    assert resolved.status.value == "RESOLVED"


def test_information_gap_lifecycle(service, incident):
    gap = service.add_information_gap(
        incident.id, "Customer impact unknown", GapImportance.CRITICAL
    )
    assert gap.status.value == "OPEN"
    resolved = service.resolve_information_gap(incident.id, gap.id)
    assert resolved.status.value == "RESOLVED"


def test_clarity_score_reflects_open_conflicts_and_gaps(service, incident):
    baseline = service.compute_clarity_score(incident.id)
    assert baseline.score == 100
    assert baseline.root_cause_confirmed is False

    service.add_information_gap(incident.id, "Customer impact unknown", GapImportance.CRITICAL)
    claim_a = service.add_claim(
        incident.id, "a", "Database instability", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, 0.5
    )
    claim_b = service.add_claim(
        incident.id, "b", "Database appears healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, 0.5
    )
    service.add_conflict(incident.id, claim_a.id, claim_b.id, ConflictType.DATABASE_HEALTH, "x")

    after = service.compute_clarity_score(incident.id)
    assert after.score < baseline.score
    assert after.critical_information_gaps == 1
    assert after.open_conflicts == 1


def test_root_cause_not_confirmed_by_default(service, incident):
    summary = service.generate_final_summary(incident.id)
    assert summary.root_cause_confirmed is False
    assert summary.root_cause_statement == "Root cause remains unconfirmed."


def test_external_action_requires_human_approval_before_execution(service, incident):
    ea = service.propose_external_action(
        incident.id,
        ExternalActionType.SLACK_MESSAGE,
        {"channel": "#payments-incident", "text": "Update"},
    )
    with pytest.raises(InvalidStateTransitionError):
        service.mark_external_action_executing(incident.id, ea.id)

    decided = service.decide_external_action(incident.id, ea.id, approved=True, approved_by="ic-alice")
    assert decided.approval_status.value == "APPROVED"

    executing = service.mark_external_action_executing(incident.id, ea.id)
    assert executing.execution_status.value == "EXECUTING"

    result = service.mark_external_action_result(
        incident.id, ea.id, succeeded=True, execution_result="Slack ts=123.45"
    )
    assert result.execution_status.value == "SUCCEEDED"


def test_external_action_cannot_execute_twice(service, incident):
    ea = service.propose_external_action(
        incident.id, ExternalActionType.SLACK_MESSAGE, {"channel": "#c", "text": "t"}
    )
    service.decide_external_action(incident.id, ea.id, approved=True, approved_by="ic-alice")
    service.mark_external_action_executing(incident.id, ea.id)
    with pytest.raises(InvalidStateTransitionError):
        service.mark_external_action_executing(incident.id, ea.id)


def test_rejected_external_action_cannot_execute(service, incident):
    ea = service.propose_external_action(
        incident.id, ExternalActionType.SLACK_MESSAGE, {"channel": "#c", "text": "t"}
    )
    service.decide_external_action(incident.id, ea.id, approved=False, approved_by="ic-alice")
    with pytest.raises(InvalidStateTransitionError):
        service.mark_external_action_executing(incident.id, ea.id)


def test_external_action_cannot_be_decided_twice(service, incident):
    ea = service.propose_external_action(
        incident.id, ExternalActionType.SLACK_MESSAGE, {"channel": "#c", "text": "t"}
    )
    service.decide_external_action(incident.id, ea.id, approved=True, approved_by="ic-alice")
    with pytest.raises(InvalidStateTransitionError):
        service.decide_external_action(incident.id, ea.id, approved=True, approved_by="ic-alice")


def test_add_risk_and_final_summary_lists_unresolved_risks(service, incident):
    service.add_risk(
        incident.id,
        "Rollback may cause data inconsistency",
        RiskSeverity.HIGH,
        confidence=0.6,
    )
    summary = service.generate_final_summary(incident.id)
    assert len(summary.unresolved_risks) == 1
