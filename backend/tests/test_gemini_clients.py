"""Tests for the Gemini client boundary (extraction/contradiction/gap).

No network calls — each real GeminiXClient is constructed normally (cheap,
no I/O) and its internal `self._client.models.generate_content` is
monkeypatched to return a real `google.genai.types.GenerateContentResponse`
-like object built from actual SDK types, not an arbitrary mock, so these
tests exercise the real response-parsing path
(`response.function_calls[i].name` / `.args`).

These prove the Gemini clients satisfy the same LLMExtractionClient /
ContradictionLLMClient / GapAssessmentLLMClient Protocols the Anthropic
clients do, and raise the same LLMCallError types the API layer already
catches. They do NOT prove the real Gemini API behaves this way — see
docs/GEMINI_PROVIDER.md for what was verified against the installed SDK
directly versus what still needs a live API smoke test.
"""

from __future__ import annotations

import pytest
from google.genai import errors, types

from app.services.contradiction.gemini_client import GeminiContradictionClient
from app.services.contradiction.llm_client import LLMCallError as ContradictionLLMCallError
from app.services.contradiction.schemas import CONTRADICTION_TOOL_NAME
from app.services.extraction.gemini_client import GeminiExtractionClient
from app.services.extraction.llm_client import LLMCallError as ExtractionLLMCallError
from app.services.extraction.schemas import EXTRACTION_TOOL_NAME
from app.services.information_gaps.gemini_client import GeminiGapAssessmentClient
from app.services.information_gaps.llm_client import LLMCallError as GapLLMCallError
from app.services.information_gaps.schemas import GAP_ASSESSMENT_TOOL_NAME


class FakeResponse:
    """Minimal stand-in for GenerateContentResponse — only `function_calls`
    is exercised by the client code, so only that is faked, but the calls
    themselves are real `types.FunctionCall` instances."""

    def __init__(self, function_calls):
        self.function_calls = function_calls


# ---------------------------------------------------------------------
# Construction / missing key
# ---------------------------------------------------------------------


def test_extraction_client_requires_api_key():
    with pytest.raises(ExtractionLLMCallError):
        GeminiExtractionClient("", "gemini-2.5-flash")


def test_contradiction_client_requires_api_key():
    with pytest.raises(ContradictionLLMCallError):
        GeminiContradictionClient("", "gemini-2.5-flash")


def test_gap_client_requires_api_key():
    with pytest.raises(GapLLMCallError):
        GeminiGapAssessmentClient("", "gemini-2.5-flash")


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------


def test_extraction_client_returns_function_call_args(monkeypatch):
    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    payload = {"claims": [{"type": "FACT", "status": "CONFIRMED", "claim": "x", "confidence": 0.9}]}
    fake_call = types.FunctionCall(name=EXTRACTION_TOOL_NAME, args=payload)
    monkeypatch.setattr(
        client._client.models, "generate_content", lambda **kw: FakeResponse([fake_call])
    )

    result = client.extract("some prompt")
    assert result == payload


def test_extraction_client_raises_on_api_error(monkeypatch):
    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")

    def raise_error(**kwargs):
        raise errors.APIError(503, {"error": {"message": "overloaded"}})

    monkeypatch.setattr(client._client.models, "generate_content", raise_error)
    with pytest.raises(ExtractionLLMCallError):
        client.extract("some prompt")


def test_extraction_client_raises_when_no_function_call_returned(monkeypatch):
    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    monkeypatch.setattr(client._client.models, "generate_content", lambda **kw: FakeResponse([]))
    with pytest.raises(ExtractionLLMCallError):
        client.extract("some prompt")


def test_extraction_client_raises_when_wrong_function_name_returned(monkeypatch):
    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    wrong_call = types.FunctionCall(name="some_other_tool", args={})
    monkeypatch.setattr(
        client._client.models, "generate_content", lambda **kw: FakeResponse([wrong_call])
    )
    with pytest.raises(ExtractionLLMCallError):
        client.extract("some prompt")


def test_extraction_client_handles_none_function_calls(monkeypatch):
    """response.function_calls is documented as Optional — None when the
    model returns no parts with a function_call at all."""
    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    monkeypatch.setattr(client._client.models, "generate_content", lambda **kw: FakeResponse(None))
    with pytest.raises(ExtractionLLMCallError):
        client.extract("some prompt")


# ---------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------


def test_contradiction_client_returns_function_call_args(monkeypatch):
    client = GeminiContradictionClient("fake-key", "gemini-2.5-flash")
    payload = {"conflicts": True, "conflict_type": "DATABASE_HEALTH", "explanation": "x"}
    fake_call = types.FunctionCall(name=CONTRADICTION_TOOL_NAME, args=payload)
    monkeypatch.setattr(
        client._client.models, "generate_content", lambda **kw: FakeResponse([fake_call])
    )

    result = client.assess("claim a vs claim b")
    assert result == payload


def test_contradiction_client_raises_on_api_error(monkeypatch):
    client = GeminiContradictionClient("fake-key", "gemini-2.5-flash")

    def raise_error(**kwargs):
        raise errors.APIError(500, {"error": {"message": "boom"}})

    monkeypatch.setattr(client._client.models, "generate_content", raise_error)
    with pytest.raises(ContradictionLLMCallError):
        client.assess("claim a vs claim b")


# ---------------------------------------------------------------------
# Gap assessment
# ---------------------------------------------------------------------


def test_gap_client_returns_function_call_args(monkeypatch):
    client = GeminiGapAssessmentClient("fake-key", "gemini-2.5-flash")
    payload = {"dimensions": [{"dimension": "CUSTOMER_IMPACT", "covered": False, "gap_description": "unknown"}]}
    fake_call = types.FunctionCall(name=GAP_ASSESSMENT_TOOL_NAME, args=payload)
    monkeypatch.setattr(
        client._client.models, "generate_content", lambda **kw: FakeResponse([fake_call])
    )

    result = client.assess("incident context")
    assert result == payload


def test_gap_client_raises_when_no_function_call_returned(monkeypatch):
    client = GeminiGapAssessmentClient("fake-key", "gemini-2.5-flash")
    monkeypatch.setattr(client._client.models, "generate_content", lambda **kw: FakeResponse([]))
    with pytest.raises(GapLLMCallError):
        client.assess("incident context")


# ---------------------------------------------------------------------
# End-to-end through ExtractionService: proves retry/degrade behavior
# is unchanged when Gemini is the provider underneath, not just that the
# raw client parses responses correctly.
# ---------------------------------------------------------------------


def test_extraction_service_validates_gemini_output_and_returns_claim(monkeypatch):
    from app.services.extraction.schemas import ExtractionContext
    from app.services.extraction.service import ExtractionService

    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    payload = {
        "claims": [
            {
                "type": "FACT",
                "status": "CONFIRMED",
                "claim": "Payment API is returning 503 errors",
                "confidence": 0.95,
                "evidence": "checked dashboard",
            }
        ]
    }
    monkeypatch.setattr(
        client._client.models,
        "generate_content",
        lambda **kw: FakeResponse([types.FunctionCall(name=EXTRACTION_TOOL_NAME, args=payload)]),
    )

    context = ExtractionContext(
        incident_title="Payment API outage", speaker_name="Alice", utterance_text="checked, it's 503s"
    )
    response = ExtractionService(client).extract(context)

    assert len(response.claims) == 1
    assert response.claims[0].claim == "Payment API is returning 503 errors"


def test_extraction_service_retries_gemini_client_on_invalid_schema_then_succeeds(monkeypatch):
    from app.services.extraction.schemas import ExtractionContext
    from app.services.extraction.service import ExtractionService

    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")
    bad_args = {"claims": [{"type": "NOT_A_TYPE", "status": "CONFIRMED", "claim": "x", "confidence": 0.5}]}
    good_args = {
        "claims": [
            {"type": "FACT", "status": "CONFIRMED", "claim": "Payment API is down", "confidence": 0.9, "evidence": "checked"}
        ]
    }
    responses = [
        FakeResponse([types.FunctionCall(name=EXTRACTION_TOOL_NAME, args=bad_args)]),
        FakeResponse([types.FunctionCall(name=EXTRACTION_TOOL_NAME, args=good_args)]),
    ]
    calls = {"n": 0}

    def fake_generate(**kw):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    monkeypatch.setattr(client._client.models, "generate_content", fake_generate)

    context = ExtractionContext(incident_title="x", speaker_name="Alice", utterance_text="y")
    response = ExtractionService(client).extract(context)

    assert calls["n"] == 2
    assert len(response.claims) == 1
    assert response.claims[0].type.value == "FACT"


def test_extraction_service_degrades_gracefully_on_repeated_gemini_failure(monkeypatch):
    from app.services.extraction.schemas import ExtractionContext
    from app.services.extraction.service import ExtractionService

    client = GeminiExtractionClient("fake-key", "gemini-2.5-flash")

    def always_fail(**kw):
        raise errors.APIError(503, {"error": {"message": "unavailable"}})

    monkeypatch.setattr(client._client.models, "generate_content", always_fail)

    context = ExtractionContext(incident_title="x", speaker_name="Alice", utterance_text="y")
    response = ExtractionService(client).extract(context)

    assert response.claims == []
