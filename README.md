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

Not yet implemented: contradiction engine, information gap engine, Slack
integration, Agora integration, voice summaries, frontend, demo replay
mode. These land in subsequent slices per the priority order in the spec.

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

28/28 tests pass, covering: claim creation/evidence gating, the "a repeated
hypothesis is never auto-confirmed" rule, action lifecycle transitions,
conflict detection (both claims preserved, marked `DISPUTED`) and
evidence-gated resolution, information gap lifecycle, the deterministic
clarity score, the final summary's explicit "root cause remains
unconfirmed" default, the external-action approval gate (including
rejection and duplicate-execution protection), fact/hypothesis/decision/
action/risk extraction, the confirmed-without-evidence safety downgrade,
extraction retry-then-succeed and retry-exhausted-degrades-gracefully, and
role-hint updates never overwriting an explicit human correction.

Extraction tests run against a fake LLM client at the same interface the
real Anthropic client implements (`LLMExtractionClient`), so they're
deterministic and need no API key. The real Anthropic integration
(`AnthropicExtractionClient`) is exercised by hand via `LLM_API_KEY` once
that's configured — the endpoint returns a clean `503` if it isn't.

API is browsable at `http://127.0.0.1:8000/docs` once running.
