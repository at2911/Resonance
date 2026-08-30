# Gemini Provider — Verified Contract and Status

Free-tier-friendly development alternative to Anthropic, selected via
`LLM_PROVIDER=gemini`. This document records what was actually verified
before writing the Gemini client code, labeled by confidence, per the same
"never invent an API" standard used for `docs/AGORA_INTEGRATION.md`.

## What was verified, and how

Unlike the Agora integration (where the real docs pages sometimes 404'd to
automated fetches and verification relied partly on search-engine
synthesis), the Gemini SDK is a local Python package. Every claim below
was confirmed by **installing `google-genai==2.20.0` into the project's
own venv and inspecting the real, installed types directly** —
`inspect.signature(...)`, `.model_fields.keys()`, `dir(...)` — not by
reading documentation and trusting it. This is strictly higher-confidence
than anything in the Agora doc.

One data point on why this mattered: an initial `WebFetch` against
`ai.google.dev/gemini-api/docs/function-calling` returned a plausible-
looking but **wrong** API shape (`client.interactions.create(...)`,
`tool_choice.allowed_tools`) that does not match the real SDK at all. A
second fetch against `googleapis.github.io/python-genai/` (the official
SDK reference) gave a shape consistent with what installing and
inspecting the package confirmed. Direct package inspection resolved the
discrepancy — treat any single doc fetch as unverified until cross-checked
against something more authoritative or, better, the actual installed
code.

### Confirmed by direct inspection of the installed SDK:

- Client construction: `genai.Client(api_key=...)`.
- Call shape: `client.models.generate_content(model: str, contents: str, config: GenerateContentConfig)`.
- Function declaration: `types.FunctionDeclaration(name=..., description=..., parameters_json_schema={...})`
  — `parameters_json_schema` takes a **raw JSON Schema dict directly**,
  confirmed via `FunctionDeclaration.model_fields`. This is why the
  existing `*_TOOL_SCHEMA["input_schema"]` dicts (already plain JSON
  Schema, built for Anthropic's tool-use) could be reused as-is for
  Gemini's function declarations — only the wrapper differs between
  providers, not the schema content.
- Tool wrapping: `types.Tool(function_declarations=[...])`.
- Forcing a call (never free text): `types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY", allowed_function_names=[...]))`,
  confirmed via `FunctionCallingConfig.model_fields` (`allowed_function_names`,
  `mode`, `stream_function_call_arguments`).
- Disabling automatic function *execution* (the SDK's own convenience
  feature that would try to call a real Python function): `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`
  — needed because these tool declarations don't correspond to real
  Python callables, only to a JSON shape we want back.
- Reading the result: `response.function_calls` — confirmed by reading
  the actual property source (`GenerateContentResponse.function_calls`)
  — returns `Optional[list[FunctionCall]]`, `None` when no candidate
  content part contains a function call. Each `FunctionCall` has `.name`
  (str) and `.args` (dict, already parsed — no `json.loads` needed,
  unlike OpenAI/Groq-style APIs where arguments arrive as a JSON string).
- Errors: `google.genai.errors.APIError` — confirmed to exist via
  `dir(errors)`, alongside `ClientError`, `ServerError`,
  `FunctionInvocationError`, `UnsupportedFunctionError`. Mirrors
  `anthropic.APIError` closely enough that the Gemini clients use the
  identical try/except shape the Anthropic clients use.

### Model name

Defaulted to `gemini-2.5-flash` (`GEMINI_MODEL` env var, overridable).
This is the exact model name used in the official `python-genai` SDK
reference's own function-calling example — the one source in this
exercise that was both authoritative *and* internally consistent with
directly-inspected SDK behavior. Search results surfaced other, newer-
sounding model names (`gemini-3.7-flash` and similar) with inconsistent,
unverifiable version numbers and pricing claims from low-authority SEO
content — **not used**, specifically because they could not be
cross-checked the way everything above was.

## What was NOT verified — the real gap

**No actual request has been sent to the real Gemini API.** Everything
above is verified against the SDK's Python-level contract: correct
objects, correct fields, correct call shape. What is *not* verified:

- Whether the real API, given `mode="ANY"` with exactly one allowed
  function, reliably returns a well-formed call matching the declared
  schema on the first attempt (the retry-then-degrade logic in
  `ExtractionService`/`ContradictionEngine`/`GapEngine` exists
  specifically because even Anthropic's forced tool-use isn't 100%
  reliable — Gemini's real-world reliability under this schema is
  unknown).
- Whether `gemini-2.5-flash` specifically handles the full extraction
  schema (nested arrays, enums, optional fields) as well as
  `claude-sonnet-5` does — schema complexity affects structured-output
  quality differently per model.
- Rate limits / free-tier quota behavior in practice.
- Whether a real `GEMINI_API_KEY` from Google AI Studio actually
  authenticates successfully with this exact client construction.

**Do not treat this integration as proven until a real request has been
made and inspected by hand** — see "Manual verification" below.

## Architecture

```
app/services/llm_factory.py          <- provider selection (LLM_PROVIDER)
app/services/extraction/
    llm_client.py                    <- AnthropicExtractionClient (unchanged)
    gemini_client.py                 <- GeminiExtractionClient (new)
app/services/contradiction/          <- same pair
app/services/information_gaps/       <- same pair
```

Both providers' clients implement the same three Protocols the engines
already depended on (`LLMExtractionClient.extract`,
`ContradictionLLMClient.assess`, `GapAssessmentLLMClient.assess`) — a
plain string in, a plain `dict` out. `ExtractionService`,
`ContradictionEngine`, `GapEngine`, the Pydantic schemas, the extraction
pipeline, and `IncidentStateService` are all unmodified; none of them
know or care which provider produced the dict they validate.

The factory (`app/services/llm_factory.py`) is the only new indirection —
9 FastAPI dependency-provider functions across `app/api/conversation.py`
and `app/api/agora.py` that used to construct `Anthropic*Client(...)`
directly now call `build_extraction_client(settings)` /
`build_contradiction_client(settings)` / `build_gap_assessment_client(settings)`
instead. Everything else about those functions — the try/except mapping
to `HTTPException(503, ...)`, the webhook route's `get_optional_*`
variants that return `None` instead of raising (so an unsigned webhook
request still gets checked by `verify_signature()` before any LLM-config
concern, per the ordering fix in `docs/AGORA_INTEGRATION.md` §5) — is
unchanged in shape, just now catching `UnsupportedProviderError` too.

## A real dependency conflict this surfaced (fixed)

Installing `google-genai==2.20.0` genuinely requires `httpx>=0.28` and
`pydantic>=2.12.5` — both incompatible with what was previously pinned
(`httpx==0.27.2`, `pydantic==2.9.2`). `httpx==0.28.1` in particular broke
the *existing* `anthropic==0.34.2` client at construction time (it still
passed a `proxies` kwarg httpx 0.28 removed) — a real break to the
Anthropic path this project already depended on, caught only because the
new factory tests were the first tests in the whole suite to actually
construct a real `Anthropic*Client` (every existing test used the
Protocol-level fakes exclusively).

Fixed by bumping `anthropic` to `0.125.0` — the latest release still on
the same `0.x` line as the previous pin (Anthropic did not cut `1.0.0`
until well after `0.34.2`), chosen specifically to minimize risk of an
unrelated breaking API change versus jumping to the new `1.x` major.
Verified directly: `messages.create` still accepts `model`, `max_tokens`,
`system`, `tools`, `tool_choice`, `messages`; `anthropic.APIError` still
exists; full 121-test suite passes; a live `uvicorn` process was hit over
real HTTP with both `LLM_PROVIDER=anthropic` (default) and
`LLM_PROVIDER=gemini` and produced the correct provider-specific "not
configured" error in each case. `pydantic` was bumped to `2.12.5` (same
major version, v2 — Pydantic's own compatibility guarantee) to satisfy
`google-genai`'s floor; the full test suite (heavily Pydantic-model-based
throughout the project) passed unchanged after the bump.

## Manual verification against the real Gemini API (not yet done)

1. Get a key from Google AI Studio (free tier).
2. `backend/.env`: set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=<key>`.
3. Restart the backend, `POST /incidents` to create one, then
   `POST /incidents/{id}/utterances` with a real sentence, e.g.
   `{"speaker_name": "Alice", "text": "Payment API is returning 503s, I checked the dashboard"}`.
4. Confirm a `FACT`/`CONFIRMED` claim actually appears in the response
   and in `GET /incidents/{id}` — not just that the call returns 200.
5. Try a hypothesis ("I think the database pool is exhausted") and
   confirm it does NOT come back `CONFIRMED`.
6. Watch the backend logs for `extraction_attempt_failed` /
   `extraction_degraded` — if Gemini's forced-tool-call reliability is
   worse than Anthropic's in practice, it will show up here as retries or
   degraded (empty) extractions.

**This procedure has not been run.** No Gemini API key was available in
this session.
