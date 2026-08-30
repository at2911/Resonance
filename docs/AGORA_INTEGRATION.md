# Agora Conversational AI Integration — Verified Contract

This document records what was actually verified against current Agora
documentation before writing any integration code, per the project's
"never invent an API" rule. Every claim below is labeled by confidence:

- **VERIFIED (direct fetch)** — retrieved directly from a `docs.agora.io`
  page in this session.
- **VERIFIED (search synthesis)** — corroborated by Agora-hosted search
  results/snippets but not confirmed by a direct page fetch (the `/join`
  reference page itself returned HTTP 404 to automated fetches in this
  session — possibly a JS-rendered doc page that doesn't serve a static
  fallback to non-browser clients). Treat as high-confidence, not
  certain — **verify against the Agora Console / live docs before a real
  session**, since request-body field names are exactly where a stale or
  synthesized answer is most likely to be subtly wrong.
- **ARCHITECTURAL FINDING** — not an API detail, but a real constraint on
  how this integration can work at all, discovered during verification.

Sources consulted are linked inline.

## 1. Base URL and REST surface

**VERIFIED (direct fetch + search synthesis).**

```
https://api.agora.io/api/conversational-ai-agent/v2/projects/<appid>
```

Endpoints confirmed to exist under this base:
- `POST {base}/join` — start a Conversational AI agent
  ([Start a conversational AI agent](https://docs.agora.io/en/conversational-ai/rest-api/join))
- `POST {base}/leave` — stop an agent
- `GET`/`POST {base}/agent/{agent_id}/query` — query agent status
  ([Query agent status](https://docs.agora.io/en/conversational-ai/rest-api/agent/query))
- `{base}/agent/{agent_id}/update` — update a running agent's configuration
  ([Update agent configuration](https://docs.agora.io/en/conversational-ai/rest-api/agent/update))

The exact HTTP verb and path shape of `leave`/`query`/`update` (whether
`agent_id` is a path segment or a body field) was **not** confirmed by a
direct fetch — the reference pages describe them narratively without a
verbatim example request. `join` is the only endpoint this integration
calls automatically; `leave` is called with a best-effort body shape (see
`rest_client.py`) that should be spot-checked against the Console/docs
before a real session.

## 2. Authentication

**VERIFIED (search synthesis, consistent with every other Agora RESTful
API — Signaling, Cloud Recording, Video Calling all document the identical
scheme):**

HTTP Basic Auth: `Authorization: Basic base64(customer_id:customer_secret)`.

This is a **different credential pair** from `AGORA_APP_ID` /
`AGORA_APP_CERTIFICATE` (which sign RTC/RTM tokens for clients joining the
channel, not REST calls to the Conversational AI Engine). Both are
required and are configured separately:

- `AGORA_APP_ID` / `AGORA_APP_CERTIFICATE` — RTC token minting.
- `AGORA_CUSTOMER_KEY` / `AGORA_CUSTOMER_SECRET` — REST API Basic Auth.

## 3. Starting an agent (`POST /join`)

**VERIFIED (search synthesis of Agora blog/tutorial examples and the
release-notes page, which was fetched directly and confirms the field
names below as real, versioned API parameters — but no single fetched
page showed one complete example request body).**

Request body shape:

```json
{
  "name": "<unique agent instance name, cannot be reused while active>",
  "properties": {
    "channel": "<RTC channel name>",
    "token": "<RTC token for the agent's own uid>",
    "agent_rtc_uid": "<agent's uid in the channel; '0' = random>",
    "remote_rtc_uids": ["*"],
    "enable_string_uid": false,
    "idle_timeout": 300,
    "asr": { "vendor": "...", "language": "en-US", "params": {} },
    "llm": { "vendor": "...", "system_messages": [...], "params": {} },
    "tts": { "vendor": "...", "params": {} },
    "turn_detection": { "mode": "...", "config": {} },
    "advanced_features": { "enable_rtm": true },
    "parameters": { "data_channel": "rtm" }
  }
}
```

- `asr`/`llm`/`tts` require a specific vendor's credentials and are
  deployment-specific — this integration does **not** hardcode a vendor
  and instead passes through whatever config is supplied at session-start
  time (see §7). Guessing a default vendor here would be inventing
  behavior the spec explicitly forbids.
- `advanced_features.enable_rtm: true` and `parameters.data_channel: "rtm"`
  are required to get live transcript delivery at all (see §5).
- Response is expected to include an `agent_id` — this is corroborated by
  every webhook payload (§4) carrying `agent_id` as the way to correlate
  events back to a specific running agent, but the literal `/join`
  response schema was not fetched directly. Treat `agent_id` extraction in
  `rest_client.py` as best-effort pending a live check.

## 4. Webhook events (server-to-server)

**VERIFIED (direct fetch).** Sources:
[Notification event types](https://docs.agora.io/en/conversational-ai/develop/event-types),
[Handle webhook](https://docs.agora.io/en/conversational-ai/develop/webhooks).

### Envelope

Every webhook POST body:

```json
{
  "noticeId": "string",
  "productId": "number",
  "eventType": "number",
  "notifyMs": "number",
  "payload": { "...": "event-specific" }
}
```

### Signature verification

Two headers, either may be used — this integration verifies
`Agora-Signature-V2` (HMAC-SHA256 over the raw request body with the
configured webhook secret) and falls back to `Agora-Signature` (HMAC-SHA1)
only if V2 is absent:

- `Agora-Signature` — HMAC/SHA1
- `Agora-Signature-V2` — HMAC/SHA256

Delivery is **at-least-once** ("retries can happen") — the docs do not
specify exact retry count/backoff. The receiver must return `200 OK`
quickly and must tolerate redelivery, which is why every webhook is
deduplicated by `noticeId` before processing (see `agora_repository.py`).

### Event types actually handled by this integration

| Code | Name | Used for |
|------|------|----------|
| 101 | agent joined | Timeline event + session status |
| 102 | agent left | Timeline event + session status |
| 103 | agent history | **The only source of full transcript text** — `payload.contents[]`, each `{role: "user"\|"assistant", content, speech_start_ms, speech_end_ms}`. Delivered once, when the agent stops (see §5 — this is *not* real-time). |
| 110 | agent error | Timeline event (`AGORA_AGENT_ERROR`), logged, never crashes the pipeline |

Events 104 (token expiry), 111/112 (metrics), 201/202 (telephony call
state) are accepted (200 OK) but not processed — they carry no
incident-reasoning-relevant content and telephony is out of scope per the
spec's "do not overbuild" instruction.

## 5. Real-time transcript delivery — architectural finding

**ARCHITECTURAL FINDING (direct fetch,
[Display live transcripts](https://docs.agora.io/en/conversational-ai/develop/transcripts) and
[Client-side events](https://docs.agora.io/en/ai/build/handle-runtime-events/event-notifications)).**

This is the most important thing verification surfaced, and it changes
the shape of "real-time ingestion" from what the slice brief assumed:

> Live transcript segments are delivered via an RTM (Signaling) channel to
> **client SDKs** (Web/Android/iOS) through a registered event handler
> (`onTranscriptUpdated` and equivalents). The client-side-events doc
> explicitly states this is for "mobile or web client" integration and
> directs backend/server needs to **webhooks instead**. A plain backend
> process cannot subscribe to the RTM transcript stream the way a browser
> or mobile client SDK can.
>
> The webhook path's only transcript-bearing event (103, "agent history")
> is delivered **once, when the agent stops** — i.e. end-of-session, not
> turn-by-turn.

Consequence: a bare backend, with no client in the loop, genuinely cannot
get turn-by-turn transcript text from Agora in real time using only
server-to-server calls — this isn't a gap in this implementation, it's how
the product is built (the AI agent's own conversational loop *is* the
real-time consumer of ASR output; a third-party backend is a second,
asynchronous consumer via webhook history or a client relay).

**This integration handles both paths it can honestly build:**

1. **Live path (real-time, requires a thin client relay):**
   `POST /incidents/{id}/agora/transcript-events` accepts one finalized
   transcript segment at a time (`event_id`, `agora_uid`, `text`,
   `timestamp`, optional `speaker_name`). Anything holding an RTM
   subscription to the channel — a browser tab, a mobile app, a small
   Node/Python RTM listener process — can call this per utterance as soon
   as ASR finalizes it. This is a wire contract, not a UI; building the
   actual relay client is explicitly frontend/demo-harness work and is
   **not** part of this backend slice, per "do not start frontend work
   yet."
2. **Webhook path (guaranteed, end-of-session, no relay required):**
   `POST /agora/webhook` processes event 103 as a batch of utterances in
   original order once the session ends — this is the safety net that
   guarantees complete incident history even if no live relay was
   running, and reconciles/deduplicates against anything the live path
   already ingested (same `event_id` derivation, see §6).

A demo that wants to *see* facts/conflicts appear live during the call
needs path 1 running; without it, the incident still gets fully
reconstructed, just only after the call ends.

### A security bug this design surfaced, and the fix

The webhook route originally declared the extraction/contradiction/gap
engines as ordinary FastAPI `Depends()` parameters, same as every other
Agora route. That's wrong specifically for the webhook: FastAPI resolves
*every* `Depends()` parameter before the route body executes, regardless
of where the parameter is referenced in the code. Since those engine
getters raise `HTTPException(503)` when `LLM_API_KEY` isn't configured,
an unsigned or forged webhook request would hit that 503 *before*
`verify_signature()` — inside the function body — ever ran, so a request
that should have failed with `401 Unauthorized` instead came back `503`
and leaked which piece of our config was missing.

Fix: the webhook route uses `get_optional_*` variants (`app/api/agora.py`)
that return `None` instead of raising. Signature verification always runs
first; only after it succeeds does the code decide whether it can also
run extraction (falling back to "persist the raw transcript, skip
reasoning" if the optional engines came back `None` — see
`_process_agent_history`). This was caught by this slice's own live
`uvicorn` smoke test, not by the unit tests (which called the route
function directly and so never exercised FastAPI's actual dependency
resolution order) — a reminder that a real HTTP round trip finds a
different class of bug than an in-process call does.

## 6. Idempotency / deduplication strategy

- Webhook envelopes are deduplicated by `noticeId` (exact redelivery of
  the same webhook is a no-op).
- Each `agent history` transcript entry gets a synthesized, deterministic
  `event_id` = `sha256(agent_id, index_in_contents, role, content,
  speech_start_ms)` truncated — so if the same history is redelivered with
  overlapping content, or if the live relay already ingested the same
  utterance under an equivalent synthesized ID, the second arrival is
  recognized as a duplicate and produces no new claim/action/timeline
  entry (see `adapter.py` / `agora_repository.py`).
- Live-relay segments carry a caller-supplied `event_id` — the relay is
  responsible for generating it once per finalized utterance (e.g. a
  UUID); the backend only deduplicates against previously-seen IDs for
  that incident.
- This is independent of, and does not change, the existing Slack
  external-action idempotency (approval → execute → result state
  machine) from the previous slice.

## 7. Speaker identity

**ARCHITECTURAL FINDING.** Agora's `agent history` webhook format
distinguishes only `role: "user" | "assistant"` — it does not disambiguate
between multiple simultaneous human speakers on a call. Real multi-speaker
attribution (Alice vs. Bob) is only available to whatever is closest to
the actual RTC stream — i.e. a client relay that knows its own
participant's `agora_uid` and attaches it when forwarding a segment via
path 1 above.

This integration never assumes an Agora uid equals an application
`Participant` id. `app/services/agora/identity.py` maintains an explicit
`agora_uid -> participant_id` map per incident: an unseen uid gets a new
`Participant` created with `role=UNKNOWN, role_confidence=0.0` (uncertainty
represented explicitly, not guessed), and role recognition then proceeds
exactly as it already does for manually-posted utterances — through the
extraction layer's `speaker_role_hint` and
`IncidentStateService.update_role_if_more_confident`, unchanged from the
previous slice.

## 8. Token generation

**VERIFIED (search synthesis — package exists on PyPI, API confirmed by
multiple independent sources including the official `AgoraIO-Community`
GitHub org).** `agora-token-builder` on PyPI:

```python
from agora_token_builder import RtcTokenBuilder
token = RtcTokenBuilder.buildTokenWithUid(
    app_id, app_certificate, channel_name, uid, role, privilege_expired_ts
)
```

Flagged limitation: this package has had no new PyPI release in the last
12 months per its Snyk/Libraries.io health data. It is functionally
adequate (token format hasn't changed) but should be revisited if Agora
ships a maintained successor before a real production deployment.

## 9. What was NOT implemented (explicitly out of scope this slice)

Per the spec's "do not overbuild": telephony (events 201/202), avatar
features, MCP tool servers, multi-LLM-model orchestration inside the
Agora agent itself, and any specific ASR/LLM/TTS vendor default. Session
creation accepts these as pass-through configuration; this integration
does not choose a vendor on the caller's behalf.

## 10. Manual real-Agora verification procedure

This cannot be executed in this development environment (no live Agora
project, no browser/mobile client, non-interactive). To actually verify
against a real Agora project:

1. Create an Agora project in the Console; note `App ID`, generate an
   `App Certificate`, and generate a `Customer ID` / `Customer Secret`
   under RESTful API credentials.
2. Configure a Conversational AI webhook callback URL pointing at
   `POST https://<your-host>/agora/webhook` and note the generated
   webhook secret; set `AGORA_WEBHOOK_SECRET`.
3. Fill in `.env` with `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`,
   `AGORA_CUSTOMER_KEY`, `AGORA_CUSTOMER_SECRET`, `AGORA_WEBHOOK_SECRET`.
4. `POST /incidents/{id}/agora/session` with real ASR/LLM/TTS vendor
   config for your account — verify a 200 with a real `agent_id` and RTC
   join token, and that the agent actually appears connected in the
   Agora Console for that channel.
5. Join the returned channel from two separate real or test RTC clients
   (e.g. Agora's own web demo, or a minimal client using the Web SDK) and
   speak.
6. Confirm `POST /agora/webhook` is being hit (check server logs / the
   `RawConversationEvent`s persisted for the incident) once the session
   ends, and that the transcript in `agent history` reconstructs into
   claims/timeline entries via the existing pipeline.
7. Optionally build a minimal RTM-listening relay to exercise
   `POST /incidents/{id}/agora/transcript-events` for true real-time
   ingestion during the call, and confirm live claim/conflict/action
   creation and the existing Slack approval flow all still work exactly
   as they do for manually-posted utterances.

**This procedure has not been run** — there is no live Agora project or
client available in this session. Everything in this slice is verified
down to the mocked-boundary level (unit/integration tests against a fake
Agora REST/webhook boundary) but the "real Agora smoke test" from the
slice brief remains outstanding and requires the user (or a follow-up
session with real credentials) to execute steps 1–7 above.
