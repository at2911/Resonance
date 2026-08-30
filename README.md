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

Not yet implemented: Agora integration, voice summaries, frontend, demo
replay mode. These land in subsequent slices per the priority order in the
spec.

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

63/63 tests pass, covering everything above plus: the message composer
(confirmed facts, unconfirmed vs. confirmed root cause, open action count,
critical gaps), the `SlackWebClient` error-mapping boundary (bad token,
API error, not-ok response, success), and the full propose → approve →
execute HTTP flow — including execution rejected with `409` when not yet
approved or after rejection, a failed Slack call recorded as `FAILED` with
the real error and successfully retried afterward, and a `409` on any
attempt to execute a second time after a `SUCCEEDED` result. Also verified
booting as a real `uvicorn` process (not just via in-process TestClient)
and hit over actual HTTP.

Extraction/contradiction/gap tests all run against fake LLM clients at the
same interfaces the real Anthropic clients implement (`LLMExtractionClient`,
`ContradictionLLMClient`, `GapAssessmentLLMClient`); Slack tests run
against a fake at the `SlackClient` interface the real `SlackWebClient`
implements. All deterministic, no API key or Slack workspace needed. The
real integrations are exercised by hand via `LLM_API_KEY` /
`SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID` once configured — endpoints return a
clean `503` if they aren't.

API is browsable at `http://127.0.0.1:8000/docs` once running.
