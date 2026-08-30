# Dangling Pointers — Voice AI Incident Commander

EchoSphere 2026 hackathon submission (PS41). See project spec for full
product/architecture rationale. This README covers only how to run what
exists so far.

## Status

Implemented: **Incident State Engine** (P0 #1) — the canonical, strongly
typed `IncidentState` model, the in-memory repository, the service that
owns all state transitions (evidence-gated claim/conflict resolution,
action lifecycle, human-approval-gated external actions with duplicate-
execution protection), and a minimal FastAPI surface over it.

Not yet implemented: LLM extraction, contradiction engine, information gap
engine, Slack integration, Agora integration, voice summaries, frontend,
demo replay mode. These land in subsequent slices per the priority order in
the spec.

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

17/17 tests pass, covering: claim creation/evidence gating, the "a repeated
hypothesis is never auto-confirmed" rule, action lifecycle transitions,
conflict detection (both claims preserved, marked `DISPUTED`) and
evidence-gated resolution, information gap lifecycle, the deterministic
clarity score, the final summary's explicit "root cause remains
unconfirmed" default, and the external-action approval gate (including
rejection and duplicate-execution protection).

API is browsable at `http://127.0.0.1:8000/docs` once running.
