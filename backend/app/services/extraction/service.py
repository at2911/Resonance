"""ExtractionService: turns one utterance into a validated ExtractionResponse.

This service owns retry and degradation behavior but never owns incident
state — it hands back a validated, structured result and lets the caller
(app/services/extraction/pipeline.py) decide how to fold it into the
IncidentState. If the LLM fails or returns something that doesn't validate,
this service retries once with a corrective prompt and, failing that,
returns an empty ExtractionResponse rather than raising — a bad model
response must never crash the conversation pipeline or corrupt state (see
project failure-handling principles).
"""

from __future__ import annotations

import logging
import time
import uuid

from pydantic import ValidationError

from app.services.extraction.llm_client import LLMCallError, LLMExtractionClient, build_context_prompt
from app.services.extraction.schemas import ExtractionContext, ExtractionResponse

logger = logging.getLogger("extraction")


class ExtractionService:
    def __init__(self, llm_client: LLMExtractionClient, max_attempts: int = 2) -> None:
        self._llm_client = llm_client
        self._max_attempts = max_attempts

    def extract(self, context: ExtractionContext) -> ExtractionResponse:
        correlation_id = uuid.uuid4().hex
        prompt = build_context_prompt(context)
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            start = time.monotonic()
            try:
                raw = self._llm_client.extract(prompt)
                result = ExtractionResponse.model_validate(raw)
            except (LLMCallError, ValidationError) as e:
                last_error = e
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.warning(
                    "extraction_attempt_failed",
                    extra={
                        "correlation_id": correlation_id,
                        "attempt": attempt,
                        "processing_time_ms": round(elapsed_ms, 1),
                        "error": str(e),
                    },
                )
                if attempt < self._max_attempts:
                    prompt = (
                        prompt
                        + f"\n\nYour previous response was invalid: {e}. "
                        + "Call extract_incident_claims again with a corrected, schema-valid response."
                    )
                continue
            else:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "extraction_succeeded",
                    extra={
                        "correlation_id": correlation_id,
                        "attempt": attempt,
                        "processing_time_ms": round(elapsed_ms, 1),
                        "claims_extracted": len(result.claims),
                    },
                )
                return result

        logger.error(
            "extraction_degraded",
            extra={"correlation_id": correlation_id, "error": str(last_error)},
        )
        return ExtractionResponse(claims=[])
