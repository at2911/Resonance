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

Not yet implemented: Slack integration, Agora integration, voice
summaries, frontend, demo replay mode. These land in subsequent slices per
the priority order in the spec.

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

45/45 tests pass, covering everything above plus: gap creation with correct
deterministic importance, idempotent gap resolution once a dimension
becomes covered, no duplicate gaps for the same dimension, safe
degradation (no state changes) on repeated LLM failure, rejection of a
response missing a required dimension, and action completion from a later
evidence-bearing utterance (including safe no-ops when the referenced
action doesn't exist or is already closed).

Extraction/contradiction/gap tests all run against fake LLM clients at the
same interfaces the real Anthropic clients implement (`LLMExtractionClient`,
`ContradictionLLMClient`, `GapAssessmentLLMClient`), so they're
deterministic and need no API key. The real Anthropic integrations are
exercised by hand via `LLM_API_KEY` once that's configured — the endpoint
returns a clean `503` if it isn't.

API is browsable at `http://127.0.0.1:8000/docs` once running.
