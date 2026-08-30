"""Tests for the Information Gap Engine: the fixed dimension checklist,
LLM-driven coverage assessment (against a fake client), idempotent
create/resolve by dimension, and safe degradation on repeated LLM failure.
"""

from __future__ import annotations

import pytest

from app.models.enums import GapImportance, IncidentDimension
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.incident_state.service import IncidentStateService
from app.services.information_gaps.llm_client import LLMCallError
from app.services.information_gaps.service import GapEngine


class FakeGapLLMClient:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    def assess(self, prompt: str) -> dict:
        self.calls += 1
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


def all_dimensions_response(uncovered: set[IncidentDimension]) -> dict:
    return {
        "dimensions": [
            {
                "dimension": d.value,
                "covered": d not in uncovered,
                "gap_description": (f"{d.value} unknown" if d in uncovered else None),
            }
            for d in IncidentDimension
        ]
    }


def test_recompute_creates_gaps_with_correct_importance(service, incident):
    fake = FakeGapLLMClient(
        [all_dimensions_response({IncidentDimension.CUSTOMER_IMPACT, IncidentDimension.START_TIME})]
    )
    result = GapEngine(fake).recompute(service, incident.id)

    by_dimension = {g.dimension: g for g in result.created}
    assert len(result.created) == 2
    assert by_dimension[IncidentDimension.CUSTOMER_IMPACT].importance == GapImportance.CRITICAL
    assert by_dimension[IncidentDimension.START_TIME].importance == GapImportance.NORMAL


def test_recompute_resolves_previously_open_gap_once_covered(service, incident):
    fake = FakeGapLLMClient(
        [
            all_dimensions_response({IncidentDimension.CUSTOMER_IMPACT}),
            all_dimensions_response(set()),
        ]
    )
    engine = GapEngine(fake)
    first = engine.recompute(service, incident.id)
    assert len(first.created) == 1

    second = engine.recompute(service, incident.id)
    assert len(second.resolved) == 1
    assert second.resolved[0].dimension == IncidentDimension.CUSTOMER_IMPACT

    stored = service.get(incident.id)
    assert stored.information_gaps[second.resolved[0].id].status.value == "RESOLVED"


def test_recompute_does_not_duplicate_gap_for_same_dimension(service, incident):
    fake = FakeGapLLMClient(
        [
            all_dimensions_response({IncidentDimension.ROLLBACK_STATUS}),
            all_dimensions_response({IncidentDimension.ROLLBACK_STATUS}),
        ]
    )
    engine = GapEngine(fake)
    first = engine.recompute(service, incident.id)
    second = engine.recompute(service, incident.id)

    assert len(first.created) == 1
    assert len(second.created) == 0
    stored = service.get(incident.id)
    assert len(stored.information_gaps) == 1


def test_recompute_degrades_gracefully_on_repeated_llm_failure(service, incident):
    fake = FakeGapLLMClient([LLMCallError("timeout"), LLMCallError("timeout")])
    result = GapEngine(fake).recompute(service, incident.id)

    assert result.degraded is True
    assert result.created == [] and result.resolved == []
    stored = service.get(incident.id)
    assert len(stored.information_gaps) == 0


def test_response_missing_a_dimension_is_rejected_and_retried(service, incident):
    incomplete = all_dimensions_response(set())
    incomplete["dimensions"] = incomplete["dimensions"][:-1]  # drop one dimension
    fake = FakeGapLLMClient([incomplete, all_dimensions_response(set())])

    result = GapEngine(fake).recompute(service, incident.id)

    assert fake.calls == 2
    assert result.degraded is False
