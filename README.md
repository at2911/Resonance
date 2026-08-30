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

Not yet implemented: information gap engine, Slack integration, Agora
integration, voice summaries, frontend, demo replay mode. These land in
subsequent slices per the priority order in the spec.

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

37/37 tests pass, covering: claim creation/evidence gating, the "a repeated
hypothesis is never auto-confirmed" rule, action lifecycle transitions,
conflict detection (both claims preserved, marked `DISPUTED`) and
evidence-gated resolution, information gap lifecycle, the deterministic
clarity score, the final summary's explicit "root cause remains
unconfirmed" default, the external-action approval gate (including
rejection and duplicate-execution protection), fact/hypothesis/decision/
action/risk extraction, the confirmed-without-evidence safety downgrade,
extraction retry-then-succeed and retry-exhausted-degrades-gracefully,
role-hint updates never overwriting an explicit human correction, the
contradiction candidate filter (entity overlap, eligible types, excludes
superseded claims), pairwise verdicts (conflict / no-conflict / fails-safe
on LLM error), duplicate-conflict prevention, and an end-to-end replay of
the spec's DB-vs-network hypothesis demo scenario proving a conflict is
actually raised.

Extraction/contradiction tests run against fake LLM clients at the same
interfaces the real Anthropic clients implement (`LLMExtractionClient`,
`ContradictionLLMClient`), so they're deterministic and need no API key.
The real Anthropic integrations are exercised by hand via `LLM_API_KEY`
once that's configured — the endpoint returns a clean `503` if it isn't.

API is browsable at `http://127.0.0.1:8000/docs` once running.
