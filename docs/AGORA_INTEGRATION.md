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

**`/join` and `/leave`: VERIFIED (direct fetch + a real successful call
against a live Agora project — see §3 and §3a). `/query`/`/update`:
VERIFIED (direct fetch) but never called by this integration.**

```
https://api.agora.io/api/conversational-ai-agent/v2/projects/<appid>
```

Endpoints:
- `POST {base}/join` — start a Conversational AI agent. **A real call
  against this returned `200` with a genuine `agent_id`** — see §3a.
  Reference page: [Start a conversational AI agent](https://docs.agora.io/en/conversational-ai/rest-api/agent/join)
  (note: the docs-site path is `rest-api/agent/join`, not `rest-api/join`
  as an earlier version of this doc had it — that stale link was never
  actually used by the code, which always called the correct API path
  above, but was corrected here).
- `POST {base}/agents/{agent_id}/leave` — stop an agent. `agent_id` is a
  **path parameter**, not a body field. This was originally implemented
  as `POST {base}/leave` with `agent_id` in the body (a guess); a real
  call against it returned a routing `404`. Corrected via a direct docs
  fetch and **verified with a real call against a known-active session,
  which succeeded** (backend returned `200`, session transitioned to
  `ENDED`) — see §3a.
- `GET`/`POST {base}/agent/{agent_id}/query` — query agent status
  ([Query agent status](https://docs.agora.io/en/conversational-ai/rest-api/agent/query)).
  Not called by this integration.
- `{base}/agent/{agent_id}/update` — update a running agent's configuration
  ([Update agent configuration](https://docs.agora.io/en/conversational-ai/rest-api/agent/update)).
  Not called by this integration.

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

**VERIFIED (direct fetch of the corrected `rest-api/agent/join` page,
plus per-vendor direct fetches for the exact ASR/LLM/TTS blocks — see
§3b — and a real successful call against a live project, §3a).**

`asr`, `llm`, and `tts` are all **required**, confirmed by direct fetch —
omitting any of them (this integration's original behavior, before this
change) would make a real `/join` call fail.

Request body shape actually used by `session_service.py`:

```json
{
  "name": "agent-<session-id>",
  "properties": {
    "channel": "<RTC channel name>",
    "token": "<RTC token for the agent's own uid>",
    "agent_rtc_uid": "<agent's uid in the channel>",
    "remote_rtc_uids": ["*"],
    "asr": { "vendor": "ares", "language": "en-US" },
    "llm": {
      "url": "https://generativelanguage.googleapis.com/v1beta/models/<GEMINI_MODEL>:streamGenerateContent?alt=sse&key=<GEMINI_API_KEY>",
      "style": "gemini",
      "params": { "model": "<GEMINI_MODEL>" },
      "system_messages": [{ "role": "user", "parts": [{ "text": "<incident-commander system prompt, see §3c>" }] }]
    },
    "tts": {
      "credential_mode": "managed",
      "vendor": "minimax",
      "params": {
        "url": "wss://api.minimax.io/ws/v1/t2a_v2",
        "model": "speech-2.8-turbo",
        "voice_setting": { "voice_id": "English_captivating_female1", "speed": 1.0 },
        "audio_setting": { "sample_rate": 44100 }
      }
    }
  }
}
```

Response includes `agent_id` — **confirmed by a real call**, not just by
inference from the webhook payload shape (see §3a).

### 3a. Real verification against a live Agora project

Performed once, against real `AGORA_APP_ID`/`AGORA_CUSTOMER_KEY`/
`AGORA_CUSTOMER_SECRET`/`GEMINI_API_KEY`, with the ASR/LLM/TTS block above
built entirely server-side (`app/services/agora/agent_config.py`):

- `POST /incidents/{id}/agora/session` with an empty body (`{"agent_uid": 0}`,
  no asr/llm/tts supplied) → backend called the real `/join` → **`200 OK`**
  with a genuine `agent_id` (format `A44...`, redacted-length-preserved in
  session notes) and our own session record correctly transitioned to
  `ACTIVE`. The incident timeline correctly recorded
  `AGORA_SESSION_STARTED` with the real agent_id embedded.
- Repeated through the actual React dashboard (not curl) — clicking
  "Start AI Incident Commander" produced the same real result, displayed
  channel name and RTC token, confirming the full frontend → backend →
  Agora path.
- `/leave`, corrected to `POST {base}/agents/{agent_id}/leave`, was
  verified twice: once against a session that had likely already expired
  (no participant had joined) — returned a structured `TaskNotFound`
  error rather than a routing 404, strong evidence the endpoint shape is
  correct — and once against a session started and ended within seconds
  of each other (via the dashboard's "End Session" button) — **this one
  fully succeeded**, our backend returned `200`, the session transitioned
  to `ENDED`, and the timeline recorded `AGORA_SESSION_ENDED`.

**What this does NOT verify:** no human has joined the created channel
and spoken. Everything downstream of "Agora receives real audio" — ASR
transcription quality, the agent's own conversational behavior, webhook
delivery of a real `agent history` event, and the extraction pipeline
processing real (not synthetic) transcript — remains unverified pending
a real voice test, which requires a human participant this environment
cannot provide. See §10 for exact next steps.

### 3b. Per-vendor verification (ASR/LLM/TTS blocks above)

Each block was independently confirmed by a **direct fetch** of Agora's
own vendor-specific documentation page, not inferred or reused from a
different vendor's shape:

- `asr` (`vendor: "ares"`, Agora's own native ASR) — direct fetch,
  `docs.agora.io/en/conversational-ai/models/asr/ares`. No external
  credential needed.
- `llm` (Google Gemini, `style: "gemini"`) — direct fetch,
  `docs.agora.io/en/ai/models/llm/gemini`. Requires the caller's own
  Gemini API key (no Agora Managed Key documented for this vendor) — this
  integration reuses the project's existing `GEMINI_API_KEY`.
- `tts` (MiniMax, `credential_mode: "managed"`) — direct fetch,
  `docs.agora.io/en/ai/models/tts/minimax`, which explicitly states
  `params.key`/`params.group_id` are not required in managed mode. No
  external MiniMax account needed; Agora bills this through the Agora
  account instead.

This combination was chosen specifically because it requires zero new
vendor signups beyond what this project already has configured — see the
research report this implementation was based on for the alternatives
considered (Agora's `preset` parameter exists but its exact usable preset
name strings were never found in any fetchable page, so it was not used).

### 3c. Incident-commander system prompt

The agent's `llm.system_messages` uses a fixed prompt
(`AGORA_INCIDENT_COMMANDER_SYSTEM_PROMPT` in `agent_config.py`) that
explicitly forbids the same thing the rest of this system forbids: never
present a hypothesis as a confirmed root cause, never invent evidence/
owners/timestamps, and require explicit human approval for critical
actions outside the voice agent itself.

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

## 9. What was NOT implemented (explicitly out of scope)

Per the spec's "do not overbuild": telephony (events 201/202), avatar
features, MCP tool servers, and multi-LLM-model orchestration inside the
Agora agent itself. Session creation still accepts an explicit
`asr`/`llm`/`tts` override in the request body, which take priority over
the server-built default (§3) — this integration does not force a
vendor choice on the caller, it just no longer requires them to supply
one to get a working session.

Also explicitly not built: any embedded audio/RTC call UI in the
frontend. `AgoraControls.tsx` starts/stops the agent and displays the
channel name and RTC token; a human still joins the call through an
external Agora-compatible client (Agora's own web demo, Studio's test
call feature, or a custom Web/Mobile SDK integration) — building that
client is a separate, larger scope than this milestone.

## 10. Manual real-Agora verification procedure

**Steps 1–4 below have been run for real, this session, against a live
Agora project.** Steps 5+ (a human joining and speaking) have not —
this environment has no microphone/audio-call capability.

1. ✅ Real credentials configured (`AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`,
   `AGORA_CUSTOMER_KEY`, `AGORA_CUSTOMER_SECRET`, `AGORA_WEBHOOK_SECRET`,
   `GEMINI_API_KEY`) — confirmed loaded without printing any value.
2. ✅ `POST /incidents/{id}/agora/session` with an empty body — real `200`,
   real `agent_id`, session `ACTIVE`, correct timeline event. Repeated
   through the actual dashboard UI, not just curl. See §3a for the full
   record.
3. ✅ Ending a session — `POST .../agora/session/{id}/end` — real `200`,
   session `ENDED`, correct timeline event, after correcting the `/leave`
   endpoint shape (§1/§3a) based on a real failure.
4. ✅ A fresh public webhook URL was stood up (Cloudflare quick tunnel)
   and confirmed reachable (`GET /health` through it returned `200`).
   **The user still needs to register this URL in the Agora Console**
   (Notifications → Conversational AI → Receiving URL) for webhook
   delivery to actually reach it — quick tunnels are ephemeral and the
   URL changes each time one is started, so this must be redone whenever
   the tunnel restarts.
5. ⬜ Join the returned channel from a real Agora-compatible client (not
   built by this codebase — see §9) and speak several incident
   statements, including a deliberately conflicting pair.
6. ⬜ Confirm `POST /agora/webhook` receives the real `agent history`
   event once the session ends, and that it reconstructs into
   claims/hypotheses/conflicts/actions/decisions via the existing,
   unmodified pipeline.
7. ⬜ Confirm the dashboard (already polling) shows the new state,
   including at least one fact, one hypothesis, and the deliberate
   conflict.
8. ⬜ Propose a Slack update from the resulting incident and confirm the
   human-approval gate still applies exactly as it does for any other
   incident (this specific chain — Agora → conflict → Slack → approval —
   is proven against *mocked* Agora boundaries by
   `test_full_chain_agora_to_slack_with_mocked_boundaries`, but not yet
   against a real Agora-delivered transcript).
9. ⬜ Optionally build a minimal RTM-listening relay to exercise
   `POST /incidents/{id}/agora/transcript-events` for true real-time
   ingestion during the call (see §5) rather than waiting for
   end-of-session reconstruction.

Steps 5–9 require a human participant and have not been run. Do not
treat the live voice path as proven until they are.

## 11. Voice summaries — "speak the current status" (spec's remaining P0 item)

Lets a human (or the dashboard, on their behalf) ask the live agent to
speak the incident's current status out loud, via `POST
/incidents/{id}/agora/session/{id}/speak-summary`
(`app/services/agora/session_service.py::speak_summary`).

**What text gets spoken:** the exact same deterministic
`SlackMessageComposer.compose(incident)` output a human already reviews
before a Slack send — no separate LLM call composes different words for
voice than for Slack, and no wording is invented independently of
confirmed state. The response body (`SpeakSummaryResponse.spoken_text`)
always echoes the exact text sent to Agora, so it's visible even without
audio (the dashboard's "Speak Summary" button shows it inline).

**Endpoint contract — VERIFIED (search synthesis only, not direct fetch).**
The `rest-api/agent/speak` docs page itself redirects automated fetches to
an index page, the exact same JS-rendering limitation that originally hit
`/join` (§1) before a real call confirmed the corrected shape. Two
independent search-result summaries agree:

```
POST {base}/agents/{agent_id}/speak
{
  "text": "<the message to speak>",
  "priority": "INTERRUPT" | "APPEND" | "IGNORE",
  "interruptable": true | false
}
```

This is corroborated by the separately, *directly*-fetched
`develop/interrupt-agent` page, which documents the identical
interrupt/append/ignore vocabulary for the related (and now also
implemented) `POST {base}/agents/{agent_id}/interrupt` endpoint — the two
features sharing vocabulary is real evidence they're part of the same
priority-handling subsystem, not proof of the exact JSON field names.
`priority=APPEND` is this integration's deliberate default (not
`INTERRUPT`): a human mid-sentence on the call is never talked over — the
agent finishes its current turn, then speaks the summary.

**What has NOT been verified: a real call against this endpoint.** A live
end-to-end attempt was made this session — real incident, real confirmed
claim, `POST /incidents/{id}/agora/session` with real credentials — and
the underlying `/join` call itself (the already-verified endpoint from
§3a, unrelated to this new work) failed three times over ~30 seconds with
a real `500` from Agora's own infrastructure:

```json
{"detail": "The model service is temporarily unavailable. Retry later.", "reason": "InternalError"}
```

This is a genuine outage/rate-limit on Agora's (or the underlying Gemini
vendor's) side, not a bug introduced by this change — it blocked even the
previously-verified `/join` path, before `/speak` could be reached at
all. **Until a session can be started again, `/speak`'s exact field names
remain at search-synthesis confidence, not confirmed by a real call** —
treat it the same way the original `/join` shape was treated before §3a's
real verification: implemented and unit-tested against fakes (146/146
backend tests), architecturally sound, but the literal JSON Agora expects
has not been proven against a live response. If a real call 400s on field
names, `rest_client.py`'s `speak()` is the one-file fix, exactly as
`leave()` was corrected in §1.

**Manual verification procedure once Agora's service recovers:**
1. `POST /incidents/{id}/agora/session` — confirm real `200`, capture `agent_id`.
2. `POST /incidents/{id}/agora/session/{session_id}/speak-summary` — record the raw HTTP status and body.
3. If `200`: update this section's confidence label to VERIFIED (real call), noting the response shape actually returned.
4. If `4xx`/`5xx` naming a field: correct `rest_client.py::speak()` to match, exactly as `/leave` was corrected in §1, and re-verify.
5. Ideally, a human actually listening in the channel (§10) confirms the agent's TTS audibly said the composed text — this closes the loop `/join`'s real-speech gap (§10) never has.
