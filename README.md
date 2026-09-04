# Resonance — Voice AI Incident Commander

**EchoSphere 2026 hackathon submission (PS41).**

Most incident-response tools log a call as one flat transcript. Resonance
listens instead — live through a real Agora voice agent, or typed in — and
turns what's said into a structured, trustworthy incident record: every
statement tagged FACT, HYPOTHESIS, DECISION, ACTION or RISK with its own
confidence and evidence, genuine contradictions between two people's
claims caught automatically (never silently resolved), and a live
Clarity Score tracking how well the team actually understands the
incident. Nothing ever reaches a real external channel — Slack included —
without a human explicitly approving it, a rule enforced on the server,
not just hidden behind a UI.

Everything below is engineering documentation, written the way it was
built: every integration is marked as either genuinely verified against a
real service, or explicitly not yet — nothing on this page describes
something that was only assumed to work.

## Highlights

- 🎙 **Real voice input** — a live Agora Conversational AI agent (Google
  Gemini as its LLM), verified against a real session — see **Agora
  Integration** below.
- 🧠 **Epistemic safety** — facts and hypotheses are never mixed; a claim
  only becomes `CONFIRMED` when real stated evidence backs it.
- ⚠️ **Contradiction detection** — a two-stage engine (deterministic
  candidate filter, then LLM judgment on meaning) flags genuine
  disagreements between claims without ever picking a silent winner.
- ✅ **Human approval gate** — the AI can draft a Slack update; only a
  person can send it. Enforced server-side, idempotent, never double-sent.
- ▶️ **Deterministic Demo Mode** — a scripted, judge-ready 9-step replay
  through the real backend, pausable/resumable, no microphone required.
- 🧪 **146 backend + 50 frontend tests passing**, plus real (not mocked)
  verification against the live Gemini, Slack, and Agora APIs — see below.

## Status

Implemented:
- **Incident State Engine** (P0 #1) — the canonical, strongly typed
  `IncidentState` model, the in-memory repository, the service that owns
  all state transitions (evidence-gated claim/conflict resolution, action
  lifecycle, human-approval-gated external actions with duplicate-execution
  protection), and a minimal FastAPI surface over it.
- **LLM Extraction Layer** (P0 #2) — schema-constrained extraction via
  Anthropic tool-use (`backend/app/services/extraction/`). An utterance is
  turned into strictly validated claims/actions/risks; the LLM call is
  retried once on a schema-invalid response and degrades to "no claims
  extracted" rather than raising or corrupting state on repeated failure.
  A deterministic pipeline (not the LLM) maps extraction output onto real
  IncidentState mutations, and downgrades any CONFIRMED/RESOLVED claim
  missing evidence to PROBABLE instead of dropping or trusting it blindly.
  Reachable via `POST /incidents/{id}/utterances`.
- **Contradiction Engine** (P0 #4) — `backend/app/services/contradiction/`.
  Two deliberate stages: a deterministic, non-LLM candidate filter
  (`find_candidates`) narrows to claims that share an extracted entity and
  are an eligible type (FACT/HYPOTHESIS/UPDATE), then a dedicated LLM tool
  call judges each candidate pair on meaning — not opposite-keyword
  matching — returning a structured verdict with a `ConflictType` and
  explanation. Wired into the extraction pipeline: every new claim is
  checked against existing ones and a genuine conflict is recorded via the
  same `IncidentStateService.add_conflict` from slice 1, which marks both
  claims `DISPUTED` without deleting either. Fails safe — an LLM error
  never fabricates a conflict, it just skips that pair.
- **Information Gap Engine** (P0 #6) — `backend/app/services/information_gaps/`.
  Tracks a fixed, closed checklist of 12 incident dimensions from the spec
  (affected service, customer impact, rollback status, root cause, etc).
  Importance (CRITICAL vs NORMAL) per dimension is a deterministic policy
  table, not an LLM decision — it matches the spec's own example exactly
  (customer impact / rollback status CRITICAL, start time NORMAL). The LLM's
  only job is judging, from the confirmed facts/decisions/actions so far,
  whether each dimension is actually covered — a full recompute rather than
  incremental, since "is customer impact known" can't be judged one claim
  at a time. Gaps are created/resolved idempotently per dimension, so a
  dimension that becomes covered later auto-resolves its gap instead of
  leaving a stale one. On repeated LLM failure it makes no state changes at
  all (never auto-resolves a real gap or fabricates a false one).
- **Action-update-from-evidence** (part of P0 #5) — the extraction schema
  now carries `completes_action_id`: an utterance reporting a check result
  ("I checked the network, packet loss is normal") is matched against the
  incident's open actions and, if it genuinely reports on one, that action
  is moved to `COMPLETED` with the utterance's evidence attached, instead
  of only creating an unrelated new claim. Invalid or already-closed
  action references are logged and skipped, never crash the pipeline.
- **Slack Integration** (P0 #8) — `backend/app/services/slack/` +
  `backend/app/api/slack.py`. The proposed message is composed
  deterministically from real state (`SlackMessageComposer`) — no LLM in
  the loop for the exact text that goes into a real, permanent Slack
  channel — then goes through the same generic propose → approve → execute
  flow built in slice 1:
  - `POST /incidents/{id}/slack-updates` composes and proposes (PENDING).
  - `POST /incidents/{id}/external-actions/{id}/decision` approves/rejects
    (existing generic endpoint).
  - `POST /incidents/{id}/external-actions/{id}/execute` re-validates
    approval server-side, then makes the real `chat.postMessage` call.
  A failed Slack call is recorded as `FAILED` with the real error — never
  reported as success — and can be retried; the state engine's execution
  lock was tightened this slice to allow `FAILED → EXECUTING` (retry)
  while still permanently blocking re-execution after `SUCCEEDED` or a
  concurrent double-call while `EXECUTING`.

  **Real (not mocked) verification performed:** a real `chat.postMessage`
  call was made against a live Slack workspace and channel using a
  minimal-scope bot token (`chat:write` only — deliberately no read scope
  requested). The full propose → approve → send chain was driven for
  real and produced a genuine message in the channel; a second execute
  attempt against the same already-`SUCCEEDED` action was correctly
  rejected by the server without re-sending, proving the duplicate-
  execution guard holds against a real call, not just the test fakes.

- **Backend-driven Demo Mode** (spec §19) — `backend/app/services/demo/`.
  A fixed, deterministic 9-step script that calls the exact same
  `IncidentStateService` methods a real incident does — nothing about it
  is a separate fake path. Playback is lazily advanced by polling
  (`GET /demo/status`), not a background thread, so it only moves forward
  while someone is actually watching. `POST /demo/{start,pause,resume,reset}`
  give explicit human control over playback; the script deliberately halts
  itself immediately before proposing the Slack update, so even a
  rehearsed demo still requires a real click through the human-approval
  gate to finish.
- **Agora Integration** (P0 #6/slice 6) — `backend/app/services/agora/` +
  `backend/app/api/agora.py`. See **`docs/AGORA_INTEGRATION.md`** for the
  verified API contract and an important architectural finding: Agora's
  real-time transcript delivery is a client-SDK (RTM) mechanism, not
  something a bare backend can subscribe to — the backend's own webhook
  only gets the full transcript once, at session end. This integration
  handles both paths honestly: `POST /incidents/{id}/agora/transcript-events`
  (live per-utterance ingestion for a thin client/RTM relay to call) and
  `POST /agora/webhook` (server-to-server lifecycle + end-of-session
  transcript, signature-verified, at-least-once-delivery-safe). Both feed
  the *exact same* extraction → contradiction → gap → state pipeline the
  manual `/utterances` endpoint uses — Agora is just another utterance
  source, not a parallel reasoning path. Session start/end goes through
  the real `/join`/`/leave` Conversational AI REST endpoints and mints RTC
  tokens; speaker identity is never assumed to equal an Agora uid (an
  unseen uid becomes a new `UNKNOWN`-role participant, same as any other
  low-confidence role recognition already built). Every event is
  deduplicated (webhook `noticeId` + a deterministic per-utterance
  `event_id`) so redelivery can never double-create a fact/action/
  timeline entry.

  **Real (not mocked) verification performed:** `POST /incidents/{id}/agora/session`
  called against a live Agora project with no request body — the backend
  now builds a complete, working default `asr`/`llm`/`tts` config
  server-side (`app/services/agora/agent_config.py`: Agora's own ARES
  ASR, Google Gemini as the LLM via this project's existing
  `GEMINI_API_KEY`, MiniMax TTS via Agora Managed Key — zero new vendor
  signups) — returned a real `200` with a genuine `agent_id`, reproduced
  through the actual dashboard's new "Start AI Incident Commander"
  button. Ending a session was also verified for real, which caught and
  fixed a real bug: `/leave` was originally guessed with the wrong URL
  shape (a live call 404'd); corrected to
  `POST {base}/agents/{agent_id}/leave` and reverified successfully. See
  `docs/AGORA_INTEGRATION.md` §3a for the full record.

  **Still not done:** no human has joined a session and spoken — this
  environment has no microphone/audio-call capability, so ASR
  transcription, real webhook `agent history` delivery, and the
  extraction pipeline processing a real (not synthetic) transcript remain
  unverified. `docs/AGORA_INTEGRATION.md` §10 is the exact remaining
  procedure and requires a human participant.

- **Frontend Dashboard** — `frontend/` (React + TypeScript + Vite). Real
  components (`IncidentHeader`, `Timeline`, `WhatChanged`, `ClaimCard`,
  `ConflictCard`, `ActionCard`, `RiskCard`, `ParticipantCard`,
  `EvidencePanel`, `ApprovalModal`, `ClarityScore`, `InformationGaps`,
  `AgoraControls`, `DemoControls`) talking to the actual backend API —
  every function in `services/api.ts` was mapped from the real route
  files, nothing invented. `RiskCard` mirrors `ActionCard`'s shape
  (severity, status, description, confidence %, mitigation when stated)
  and reads real `incident.risks` state; `ParticipantCard` reads real
  `incident.participants` (role, role confidence, a 🎙 badge for anyone
  identified via a real Agora voice session), rendering `UNKNOWN` role at
  0% confidence honestly rather than hiding it; `WhatChanged` computes a
  recap purely from real timeline/external-action timestamps, no separate
  state of its own. `frontend/demo.html` (a single-file, dependency-free
  fallback) is kept alongside it untouched.
  See **Frontend** below.
- **Provider-agnostic LLM selection** — `LLM_PROVIDER=anthropic` (default)
  or `gemini`, so development doesn't require paid Anthropic usage. See
  **`docs/GEMINI_PROVIDER.md`** for the verified `google-genai` SDK
  contract (confirmed by installing the package and inspecting the real
  types directly, not just reading docs — one doc fetch during this work
  returned a plausible but wrong API shape, caught by that inspection).
  `app/services/llm_factory.py` is the only new indirection: 9 FastAPI
  dependency-provider functions that used to construct
  `Anthropic*Client(...)` directly now call `build_extraction_client(settings)`
  /`build_contradiction_client(settings)`/`build_gap_assessment_client(settings)`.
  `IncidentStateService`, `ExtractionService`, `ContradictionEngine`,
  `GapEngine`, the Pydantic schemas, and the extraction pipeline are all
  unchanged — both providers' clients satisfy the exact same Protocols
  those already depended on. Fixed a real dependency conflict this
  surfaced: `google-genai` requires `httpx>=0.28`/`pydantic>=2.12.5`,
  and `httpx==0.28.1` broke the *existing* pinned `anthropic==0.34.2`
  client at construction time — caught only because the new factory
  tests were the first in the suite to construct a real Anthropic client
  object. Fixed by bumping `anthropic` to `0.125.0` (same `0.x` line,
  chosen over the new `1.x` major to minimize risk) and `pydantic` to
  `2.12.5` (same v2 major); full suite re-verified after both bumps.
  **The real Gemini API has since been verified end to end**: six real
  requests across `GeminiExtractionClient` (fact and hypothesis paths) and
  `GeminiContradictionClient` (positive and negative cases), plus a full
  `POST /incidents/{id}/utterances` HTTP round trip that exercised the
  Gap Engine's real Gemini call too — see `docs/GEMINI_PROVIDER.md` for
  the full record, including the live `gemini-2.5-flash` → `404` that
  caught a wrong default model and the `gemini-3.6-flash` fix.

- **Voice summaries** — `POST /incidents/{id}/agora/session/{id}/speak-summary`
  asks the live Agora agent to speak the incident's current status out
  loud. Reuses the exact same deterministic `SlackMessageComposer` text a
  human already reviews before a Slack send — no separate wording is
  invented for voice. The `/speak` endpoint shape is search-synthesis
  verified (two independent sources, corroborated by the directly-fetched
  `/interrupt` endpoint's shared vocabulary), not yet confirmed by a real
  call — a live attempt this session was blocked by a genuine `500` from
  Agora's own model-service infrastructure (not a bug in this code; it
  blocked the already-verified `/join` too). See
  `docs/AGORA_INTEGRATION.md` §11 for the exact retry procedure.
- **Participants panel** (frontend) — the dashboard now surfaces
  `incident.participants` (name, recognized role, role confidence, a 🎙
  badge for anyone identified via a real Agora voice session) instead of
  only holding that data server-side.
- **What Changed panel** (frontend) — a recap of everything new since the
  last successfully-sent Slack update (or since the incident was created,
  if none has been sent yet), computed from the incident's own timeline —
  useful for picking the incident back up after stepping away.

Everything above landed and was verified the same night, without the
maintainer present to approve each step (explicitly authorized) — see
git log for the exact commits. Backend/frontend test counts below reflect
this work.

## Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp ../.env.example ../.env  # fill in credentials as later slices need them
uvicorn app.main:app --reload
```

Run tests:

```bash
cd backend
pytest -v
```

146/146 tests pass (up from 121 — 14 for backend-driven Demo Mode, 6 for
the Agora default ASR/LLM/TTS construction and the real-request-shaped
`AgentConfigError`/503 path), covering everything above plus:

- (Agora) event normalization (deterministic dedup-friendly IDs for
  webhook history entries, spec-shaped live-relay events), speaker
  identity mapping (unseen uid → new UNKNOWN-role participant, same uid →
  same participant, human correction/role-confidence rules unchanged),
  deduplication (live relay event_id, webhook noticeId, and webhook
  history redelivery), the agent's own speech never being run through
  extraction, malformed webhook bodies (400) and bad/missing signatures
  (401) rejected before any other processing, unassociated events
  (unknown agent_id/channel) accepted with 200 but ignored rather than
  erroring, session create/end including graceful failure when the Agora
  REST call or token minting fails, extraction-unavailable webhook
  history still preserving every raw event, and a full chain test driving
  conflict detection + action ownership + the Slack approval gate
  entirely through the Agora live-relay endpoint instead of
  manually-posted utterances.
- (Gemini/factory) the Gemini clients' response parsing (function-call
  args returned, API errors mapped to the existing `LLMCallError`, no/
  wrong function call raises), `ExtractionService`'s retry-then-degrade
  behavior proven unchanged when Gemini is the provider underneath (not
  just the raw client), and the factory tests proving
  `LLM_PROVIDER=anthropic`/`gemini` each construct the correct client
  class (and an unsupported provider name raises cleanly).

A real HTTP smoke test against a live `uvicorn` process caught a genuine
bug the unit tests missed (calling the route function directly doesn't
exercise FastAPI's actual dependency-resolution order): an unsigned Agora
webhook request was returning a misleading `503` about LLM configuration
instead of `401 Unauthorized`, because the extraction-service dependency
was resolved before the signature check ran. Fixed — see
`docs/AGORA_INTEGRATION.md` §5. **Session start/end have since been
verified against a live Agora project** (real `200`s, a genuine
`agent_id`, correct `ACTIVE`/`ENDED` transitions — see that doc's §3a).
**What's still unverified: a human joining the channel and speaking** —
ASR transcription, real webhook `agent history` delivery, and the
extraction pipeline processing a real transcript all require a live
voice participant this environment cannot provide; see §10 for the exact
remaining procedure.

Extraction/contradiction/gap tests all run against fake LLM clients at the
same interfaces the real Anthropic clients implement (`LLMExtractionClient`,
`ContradictionLLMClient`, `GapAssessmentLLMClient`); Slack tests run
against a fake at the `SlackClient` interface the real `SlackWebClient`
implements; Agora tests run against fakes at the `AgoraConversationalAIClient`
and `TokenBuilder` interfaces. All deterministic, no API key, Slack
workspace, or Agora project needed. The real integrations are exercised by
hand via `LLM_API_KEY` / `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID` /
`AGORA_APP_ID` / `AGORA_APP_CERTIFICATE` / `AGORA_CUSTOMER_KEY` /
`AGORA_CUSTOMER_SECRET` / `AGORA_WEBHOOK_SECRET` once configured —
endpoints return a clean `503` if they aren't.

API is browsable at `http://127.0.0.1:8000/docs` once running.

## Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, expects the backend on :8000
```

Talks directly to the backend (CORS is open for local dev) — no proxy
config needed. Override the backend URL with `VITE_API_BASE_URL` if it's
not on `http://127.0.0.1:8000`.

Run tests / type-check / build:

```bash
npm run test      # 50/50 — component tests, a full propose -> approve
                   # -> execute -> reject flow against a stateful mock of
                   # the API layer, Demo Mode controls, the Risks and
                   # Participants panels, What Changed, and Agora session
                   # start/speak-summary/error/end
npm run build      # tsc -b && vite build
npm run lint
```

Manually verified end-to-end with headless Chromium against the real,
running backend (not mocked): incident creation, the dashboard rendering
real facts/hypotheses/conflicts/actions/risks/gaps/timeline, the evidence
provenance toggle, a Slack-unconfigured proposal producing a graceful
error banner instead of a crash, the full Demo Mode start/pause/resume/
reset cycle, and — against a real live Agora project, not mocked —
clicking "Start AI Incident Commander" and seeing the real channel/agent
ID/RTC token appear (see `docs/AGORA_INTEGRATION.md` §3a). Zero browser
console errors in any of these runs.

`frontend/demo.html` remains as a dependency-free fallback — open it
directly in a browser (no `npm install` needed) if the real frontend can't
run for some reason.
