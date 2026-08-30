"""Provider-selection factory for the three LLM-backed engines.

Deliberately small and closed — this is not a generic multi-provider
framework, just enough indirection to pick between the two providers the
project actually uses (LLM_PROVIDER=anthropic|gemini) instead of each
FastAPI dependency provider hardcoding a concrete Anthropic client. Adding
a third provider means adding one more branch here plus one more sibling
*_client.py per engine — not a new abstraction layer.

Nothing about IncidentStateService, the extraction/contradiction/gap
*services* (retry/degrade logic), the Pydantic schemas, or the pipeline
changes because of this — they only ever depended on the Protocols
(LLMExtractionClient, ContradictionLLMClient, GapAssessmentLLMClient),
which both providers' clients satisfy identically.
"""

from __future__ import annotations

from app.config import Settings
from app.services.contradiction.gemini_client import GeminiContradictionClient
from app.services.contradiction.llm_client import AnthropicContradictionClient, ContradictionLLMClient
from app.services.extraction.gemini_client import GeminiExtractionClient
from app.services.extraction.llm_client import AnthropicExtractionClient, LLMExtractionClient
from app.services.information_gaps.gemini_client import GeminiGapAssessmentClient
from app.services.information_gaps.llm_client import AnthropicGapAssessmentClient, GapAssessmentLLMClient

SUPPORTED_PROVIDERS = ("anthropic", "gemini")


class UnsupportedProviderError(Exception):
    pass


def build_extraction_client(settings: Settings) -> LLMExtractionClient:
    if settings.llm_provider == "gemini":
        return GeminiExtractionClient(settings.gemini_api_key, settings.gemini_model)
    if settings.llm_provider == "anthropic":
        return AnthropicExtractionClient(settings.llm_api_key, settings.llm_model)
    raise UnsupportedProviderError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' — supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def build_contradiction_client(settings: Settings) -> ContradictionLLMClient:
    if settings.llm_provider == "gemini":
        return GeminiContradictionClient(settings.gemini_api_key, settings.gemini_model)
    if settings.llm_provider == "anthropic":
        return AnthropicContradictionClient(settings.llm_api_key, settings.llm_model)
    raise UnsupportedProviderError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' — supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def build_gap_assessment_client(settings: Settings) -> GapAssessmentLLMClient:
    if settings.llm_provider == "gemini":
        return GeminiGapAssessmentClient(settings.gemini_api_key, settings.gemini_model)
    if settings.llm_provider == "anthropic":
        return AnthropicGapAssessmentClient(settings.llm_api_key, settings.llm_model)
    raise UnsupportedProviderError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' — supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
