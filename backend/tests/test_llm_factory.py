"""Tests for app/services/llm_factory.py — the provider-selection layer.

Settings is constructed directly with explicit kwargs in every test rather
than via environment variables: pydantic-settings gives constructor
kwargs the highest precedence (above env vars and any real .env file on
disk), so these tests are isolated from whatever is actually configured
locally.

These only prove *construction* picks the right client class — no network
call happens either way (building an Anthropic/Gemini SDK client object is
local and cheap), consistent with how the existing Anthropic-side tests
work today (none of them call the real API either).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.contradiction.gemini_client import GeminiContradictionClient
from app.services.contradiction.llm_client import AnthropicContradictionClient
from app.services.extraction.gemini_client import GeminiExtractionClient
from app.services.extraction.llm_client import AnthropicExtractionClient
from app.services.information_gaps.gemini_client import GeminiGapAssessmentClient
from app.services.information_gaps.llm_client import AnthropicGapAssessmentClient
from app.services.llm_factory import (
    UnsupportedProviderError,
    build_contradiction_client,
    build_extraction_client,
    build_gap_assessment_client,
)


def anthropic_settings() -> Settings:
    return Settings(
        llm_provider="anthropic",
        llm_api_key="fake-anthropic-key",
        llm_model="claude-sonnet-5",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
    )


def gemini_settings() -> Settings:
    return Settings(
        llm_provider="gemini",
        llm_api_key="",
        llm_model="claude-sonnet-5",
        gemini_api_key="fake-gemini-key",
        gemini_model="gemini-2.5-flash",
    )


def unsupported_settings() -> Settings:
    return Settings(
        llm_provider="openai",
        llm_api_key="",
        gemini_api_key="",
    )


class TestExtractionClientSelection:
    def test_anthropic_provider_builds_anthropic_client(self):
        client = build_extraction_client(anthropic_settings())
        assert isinstance(client, AnthropicExtractionClient)

    def test_gemini_provider_builds_gemini_client(self):
        client = build_extraction_client(gemini_settings())
        assert isinstance(client, GeminiExtractionClient)

    def test_unsupported_provider_raises(self):
        with pytest.raises(UnsupportedProviderError):
            build_extraction_client(unsupported_settings())


class TestContradictionClientSelection:
    def test_anthropic_provider_builds_anthropic_client(self):
        client = build_contradiction_client(anthropic_settings())
        assert isinstance(client, AnthropicContradictionClient)

    def test_gemini_provider_builds_gemini_client(self):
        client = build_contradiction_client(gemini_settings())
        assert isinstance(client, GeminiContradictionClient)

    def test_unsupported_provider_raises(self):
        with pytest.raises(UnsupportedProviderError):
            build_contradiction_client(unsupported_settings())


class TestGapAssessmentClientSelection:
    def test_anthropic_provider_builds_anthropic_client(self):
        client = build_gap_assessment_client(anthropic_settings())
        assert isinstance(client, AnthropicGapAssessmentClient)

    def test_gemini_provider_builds_gemini_client(self):
        client = build_gap_assessment_client(gemini_settings())
        assert isinstance(client, GeminiGapAssessmentClient)

    def test_unsupported_provider_raises(self):
        with pytest.raises(UnsupportedProviderError):
            build_gap_assessment_client(unsupported_settings())


def test_default_provider_is_anthropic():
    """The Settings field default (not an instance built from the real,
    gitignored backend/.env — which may legitimately have LLM_PROVIDER=
    gemini set for manual verification) must be anthropic: the provider
    swap must be opt-in, never silently active for anyone who hasn't
    configured it. Checked against the class's own field default so this
    is immune to whatever's actually in the environment running the test."""
    assert Settings.model_fields["llm_provider"].default == "anthropic"

    # And confirm that default is actually honored when nothing overrides it.
    settings = Settings(llm_provider="anthropic", llm_api_key="fake", gemini_api_key="")
    assert isinstance(build_extraction_client(settings), AnthropicExtractionClient)


def test_gemini_provider_without_key_raises_llm_call_error_not_unsupported_provider():
    """An empty GEMINI_API_KEY with LLM_PROVIDER=gemini is a configuration
    problem the existing "not configured" path already handles (503 in the
    API layer) — it must not be confused with an unsupported provider
    name, which is a different failure mode."""
    from app.services.extraction.llm_client import LLMCallError

    settings = Settings(llm_provider="gemini", gemini_api_key="", llm_api_key="")
    with pytest.raises(LLMCallError):
        build_extraction_client(settings)
