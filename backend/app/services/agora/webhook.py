"""Webhook signature verification and envelope parsing
(docs/AGORA_INTEGRATION.md §4).

Verifies Agora-Signature-V2 (HMAC-SHA256) over the raw request body,
falling back to Agora-Signature (HMAC-SHA1) only if V2 is absent, exactly
as documented. Signature verification happens against the raw bytes
before any JSON parsing — parsing first and re-serializing to verify would
not reproduce the exact bytes Agora signed.
"""

from __future__ import annotations

import hashlib
import hmac

from pydantic import ValidationError

from app.services.agora.schemas import WebhookEnvelope


class WebhookVerificationError(Exception):
    pass


def verify_signature(
    secret: str,
    raw_body: bytes,
    signature_v2: str | None,
    signature_v1: str | None,
) -> None:
    if not secret:
        raise WebhookVerificationError("AGORA_WEBHOOK_SECRET is not configured")

    if signature_v2:
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature_v2):
            return
        raise WebhookVerificationError("Agora-Signature-V2 mismatch")

    if signature_v1:
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha1).hexdigest()
        if hmac.compare_digest(expected, signature_v1):
            return
        raise WebhookVerificationError("Agora-Signature mismatch")

    raise WebhookVerificationError("No Agora signature header present")


def parse_envelope(raw_body: bytes) -> WebhookEnvelope:
    try:
        return WebhookEnvelope.model_validate_json(raw_body)
    except ValidationError as e:
        raise WebhookVerificationError(f"Malformed webhook envelope: {e}") from e
