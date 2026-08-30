"""Tests for the Contradiction Engine: the deterministic candidate filter,
the LLM-based pairwise verdict (against a fake client, no network), and the
full detect-and-record flow against real IncidentState — including the
canonical demo scenario from the spec (DB hypothesis vs network hypothesis).
"""

from __future__ import annotations

import pytest

from app.models.enums import ClaimStatus, ClaimType, ConflictType
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.contradiction.llm_client import LLMCallError
from app.services.contradiction.service import ContradictionEngine, find_candidates
from app.services.extraction.pipeline import apply_extraction
from app.services.extraction.schemas import ExtractionContext
from app.services.extraction.service import ExtractionService
from app.services.incident_state.service import IncidentStateService


class FakeContradictionLLMClient:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def assess(self, prompt: str) -> dict:
        self.calls.append(prompt)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeLLMExtractionClient:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)

    def extract(self, context_prompt: str) -> dict:
        return self._responses.pop(0)


@pytest.fixture
def service() -> IncidentStateService:
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def incident(service: IncidentStateService):
    return service.create_incident("Payment API outage")


def add_claim(service, incident_id, claim, type, status, entities, confidence=0.6, speaker=None):
    return service.add_claim(
        incident_id,
        text=claim,
        normalized_claim=claim,
        type=type,
        status=status,
        confidence=confidence,
        speaker_id=speaker,
        evidence="x" if status in (ClaimStatus.CONFIRMED, ClaimStatus.RESOLVED) else None,
        entities=entities,
    )


def test_find_candidates_requires_shared_entity(service, incident):
    a = add_claim(service, incident.id, "DB instability", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "DB looks healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    c = add_claim(service, incident.id, "Deploy happened at 10am", ClaimType.FACT, ClaimStatus.CONFIRMED, ["deployment"])

    candidates = find_candidates(b, [a, c])
    assert candidates == [a]


def test_find_candidates_excludes_ineligible_types(service, incident):
    a = add_claim(service, incident.id, "Roll back the deploy", ClaimType.DECISION, ClaimStatus.CONFIRMED, ["database"])
    b = add_claim(service, incident.id, "DB looks healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    assert find_candidates(b, [a]) == []


def test_find_candidates_excludes_superseded(service, incident):
    a = add_claim(service, incident.id, "DB instability", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    service.update_claim_status(incident.id, a.id, ClaimStatus.SUPERSEDED)
    b = add_claim(service, incident.id, "DB looks healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    stored = service.get(incident.id)
    assert find_candidates(b, list(stored.claims.values())) == []


def test_assess_pair_reports_conflict(service, incident):
    a = add_claim(service, incident.id, "The database is timing out.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "The database looks healthy.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    fake = FakeContradictionLLMClient(
        [{"conflicts": True, "conflict_type": "DATABASE_HEALTH", "explanation": "Both can't be true"}]
    )
    verdict = ContradictionEngine(fake).assess_pair(a, b)
    assert verdict.conflicts is True
    assert verdict.conflict_type == ConflictType.DATABASE_HEALTH


def test_assess_pair_no_conflict(service, incident):
    a = add_claim(service, incident.id, "DB timing out", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "Deploy happened recently", ClaimType.FACT, ClaimStatus.CONFIRMED, ["database"])
    fake = FakeContradictionLLMClient([{"conflicts": False}])
    verdict = ContradictionEngine(fake).assess_pair(a, b)
    assert verdict.conflicts is False


def test_assess_pair_fails_safe_on_llm_error(service, incident):
    a = add_claim(service, incident.id, "DB timing out", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "DB healthy", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    fake = FakeContradictionLLMClient([LLMCallError("timeout")])
    verdict = ContradictionEngine(fake).assess_pair(a, b)
    assert verdict.conflicts is False


def test_detect_and_record_creates_conflict_and_disputes_claims(service, incident):
    a = add_claim(service, incident.id, "The database is timing out.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "The database looks healthy.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    fake = FakeContradictionLLMClient(
        [{"conflicts": True, "conflict_type": "DATABASE_HEALTH", "explanation": "Both can't be true"}]
    )
    conflicts = ContradictionEngine(fake).detect_and_record(service, incident.id, b)

    assert len(conflicts) == 1
    stored = service.get(incident.id)
    assert stored.claims[a.id].status == ClaimStatus.DISPUTED
    assert stored.claims[b.id].status == ClaimStatus.DISPUTED


def test_detect_and_record_does_not_duplicate_existing_conflict(service, incident):
    a = add_claim(service, incident.id, "The database is timing out.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    b = add_claim(service, incident.id, "The database looks healthy.", ClaimType.HYPOTHESIS, ClaimStatus.UNCONFIRMED, ["database"])
    fake = FakeContradictionLLMClient(
        [
            {"conflicts": True, "conflict_type": "DATABASE_HEALTH", "explanation": "x"},
            {"conflicts": True, "conflict_type": "DATABASE_HEALTH", "explanation": "x"},
        ]
    )
    engine = ContradictionEngine(fake)
    first = engine.detect_and_record(service, incident.id, b)
    second = engine.detect_and_record(service, incident.id, b)

    assert len(first) == 1
    assert len(second) == 0
    stored = service.get(incident.id)
    assert len(stored.conflicts) == 1


def test_demo_scenario_db_vs_network_hypothesis_conflict_detected(service, incident):
    """Mirrors the spec's demo: engineer raises a DB hypothesis, SRE raises
    a network hypothesis, and the system must surface CONFLICT DETECTED —
    end-to-end through extraction + contradiction, exactly as the API does.
    """
    extraction_client = FakeLLMExtractionClient(
        [
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
        ]
    )
    contradiction_client = FakeContradictionLLMClient(
        [
            {
                "conflicts": True,
                "conflict_type": "DATABASE_HEALTH",
                "explanation": "Engineer reports DB instability while SRE reports the DB is healthy",
            }
        ]
    )
    extraction_service = ExtractionService(extraction_client)
    contradiction_engine = ContradictionEngine(contradiction_client)

    ctx1 = ExtractionContext(
        incident_title=incident.title,
        speaker_name="engineer",
        utterance_text="I think the database connection pool is exhausted.",
    )
    r1 = apply_extraction(
        service, incident.id, ctx1, extraction_service.extract(ctx1), contradiction_engine
    )
    assert len(r1.conflicts) == 0

    ctx2 = ExtractionContext(
        incident_title=incident.title,
        speaker_name="sre",
        utterance_text="The database looks healthy; the network is dropping packets.",
    )
    r2 = apply_extraction(
        service, incident.id, ctx2, extraction_service.extract(ctx2), contradiction_engine
    )

    assert len(r2.conflicts) == 1
    assert r2.conflicts[0].conflict_type == ConflictType.DATABASE_HEALTH
    stored = service.get(incident.id)
    assert stored.conflicts[r2.conflicts[0].id].status.value == "OPEN"
