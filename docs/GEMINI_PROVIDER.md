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

### Model name — corrected after a real API call

Originally defaulted to `gemini-2.5-flash`, chosen because it was the
exact model name in the official `python-genai` SDK reference's own
function-calling example — at the time, the most authoritative source
available (search results surfaced newer-sounding names like
`gemini-3.7-flash` with inconsistent, unverifiable version numbers from
low-authority SEO content, deliberately not used).

**That default was wrong.** The first real request made against the live
API (see "Manual verification" below) failed with a live `404`:

```
This model models/gemini-2.5-flash is no longer available to new users.
Please update your code to use models/gemini-3.6-flash for the latest
features and improvements.
```

A doc or a search result saying a model exists is not the same as a key
actually being able to use it — model availability changes faster than
docs get updated, and varies by whether the key is "new". The default is
now `gemini-3.6-flash`, and unlike the original choice, **this one is
confirmed by an actual successful request** — see below.

## What has now actually been verified end to end

A real request was sent through the real, unmodified `GeminiExtractionClient`
against the live API (key configured in the gitignored `backend/.env`,
never logged or printed) for the utterance *"Payment failures increased
to 38 percent at 14:05 after the latest deployment."* with
`gemini-3.6-flash`. It returned a well-formed, single forced tool call on
the first attempt — no retry needed — which validated cleanly against
`ExtractionResponse` with no coercion:

```json
{
  "type": "FACT",
  "status": "CONFIRMED",
  "claim": "Payment failure rate increased to 38% at 14:05 following the latest deployment",
  "confidence": 0.95,
  "evidence": "Speaker reported payment failure rate reached 38% at 14:05 after the latest deployment.",
  "entities": ["Payment API", "latest deployment"],
  "temporal_info": "14:05, after latest deployment"
}
```

This resolves the two largest previously-open unknowns: a real
`GEMINI_API_KEY` does authenticate correctly with this exact client
construction, and the forced tool call does come back well-formed on the
first attempt for a realistic incident utterance (not the pre-scripted
ones the mocked tests use).

## What is still NOT verified

- Reliability across many/varied utterances and the full range of claim
  types (only one FACT-shaped sentence has been tried against the real
  API so far) — the retry-then-degrade logic in `ExtractionService`
  exists because even forced tool-use isn't 100% reliable in general;
  single-sample success doesn't establish a failure rate.
- The Contradiction and Gap engines specifically — only the extraction
  client has been exercised against the real API; the other two Gemini
  clients share the same verified SDK plumbing but haven't each been
  called for real yet.
- Rate limits / free-tier quota behavior under sustained use.

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

## Manual verification against the real Gemini API

**Partially done — first two checks passed against a real key.**

1. ✅ Real key configured in the gitignored `backend/.env`
   (`LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...`), confirmed loaded by the
   running app without ever printing the key value.
2. ✅ One real request through `GeminiExtractionClient` directly, for
   *"Payment failures increased to 38 percent at 14:05 after the latest
   deployment."* — returned a well-formed FACT/CONFIRMED claim on the
   first attempt, validated cleanly against `ExtractionResponse` (see
   above; this run is what caught the `gemini-2.5-flash` → `404`
   problem and confirmed `gemini-3.6-flash` as the fix).
3. ✅ One real request through the actual HTTP path,
   `POST /incidents/{id}/utterances` with *"I just checked the load
   balancer dashboard and it shows no unusual traffic spikes."* — a real
   FACT/CONFIRMED claim landed in `GET /incidents/{id}`, the timeline
   grew from 1 to 12 events, and the clarity score dropped from 100 to
   20. Notably, the **Gap Engine's own real Gemini call also succeeded**
   in the same request — it correctly assessed all 12 fixed dimensions
   and produced the right CRITICAL/NORMAL split (customer impact and
   rollback status critical, deployment/root-cause/etc. normal) —
   evidence this isn't just the extraction client working, but the
   pipeline's second independent Gemini-backed engine too.

**Still not done:**

- A hypothesis-shaped utterance ("I think the database pool is
  exhausted") has not been tried — the specific "never auto-confirms a
  hypothesis" behavior is unverified against the real API (though it's
  enforced by `ExtractionService`'s own downgrade logic regardless of
  what the model returns, so this is a defense-in-depth check, not a
  single point of failure).
- The Contradiction Engine's real Gemini client has not been exercised
  (only one claim existed in the test incident, so no candidate pair
  ever reached `assess_pair`).
- Reliability across many utterances / rate-limit behavior under
  sustained use — only two real requests have been made total.
