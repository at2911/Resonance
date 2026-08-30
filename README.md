# Dangling Pointers — Voice AI Incident Commander

EchoSphere 2026 hackathon submission (PS41). See project spec for full
product/architecture rationale. This README covers only how to run what
exists so far.

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

  **Not yet done:** the real Agora smoke test (live project, live room,
  two real speakers) — there is no live Agora project or client available
  in this environment. Everything up to the mocked-boundary level is
  tested and verified; §10 of the integration doc is the manual procedure
  to actually run it against a real Agora account.

- **Frontend Dashboard** — `frontend/` (React + TypeScript + Vite). Real
  components (`IncidentHeader`, `Timeline`, `ClaimCard`, `ConflictCard`,
  `ActionCard`, `EvidencePanel`, `ApprovalModal`, `ClarityScore`,
  `InformationGaps`) talking to the actual backend API — every function in
  `services/api.ts` was mapped from the real route files, nothing invented.
  `frontend/demo.html` (a single-file, dependency-free fallback built for
  the live demo) is kept alongside it untouched. See **Frontend** below.
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
  **The real Gemini API has not been called** — see that doc's closing
  section for the manual verification procedure.

Not yet implemented: voice summaries, backend-driven demo replay mode
(start/pause/resume/reset). These land in subsequent slices per the
priority order in the spec.

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

121/121 tests pass, covering everything above plus:

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
`docs/AGORA_INTEGRATION.md` §5. **The real Agora smoke test (live project,
live room, real speech) has not been run** — no live Agora credentials or
client are available in this environment; see that doc's §10 for the
manual procedure.

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
npm run test      # 21/21 — component tests plus a full propose -> approve
                   # -> execute -> reject flow against a stateful mock of
                   # the API layer
npm run build      # tsc -b && vite build
npm run lint
```

Manually verified end-to-end with headless Chromium against the real,
running backend (not mocked): incident creation, the dashboard rendering
real facts/hypotheses/conflicts/actions/gaps/timeline, the evidence
provenance toggle, and a Slack-unconfigured proposal producing a graceful
error banner instead of a crash. Zero browser console errors.

`frontend/demo.html` remains as a dependency-free fallback — open it
directly in a browser (no `npm install` needed) if the real frontend can't
run for some reason.
