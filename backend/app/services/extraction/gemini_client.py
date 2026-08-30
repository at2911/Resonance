"""Gemini equivalent of AnthropicExtractionClient (llm_client.py) — same
Protocol (LLMExtractionClient.extract), same forced-tool-call contract and
error-handling shape, different wire format underneath. See
docs/GEMINI_PROVIDER.md for what was verified against the real
`google-genai` SDK before writing this (installed and inspected directly,
not just read from docs) versus what still needs a live API check.

Reuses the exact same EXTRACTION_TOOL_SCHEMA/SYSTEM_PROMPT the Anthropic
client uses — the JSON Schema in EXTRACTION_TOOL_SCHEMA["input_schema"] is
portable between providers; only the request/response wrapper differs.
Raises the same LLMCallError the Anthropic client raises, so the
call sites in app/api/*.py that already catch it need no changes.
"""

from __future__ import annotations

from app.services.extraction.llm_client import SYSTEM_PROMPT, LLMCallError
from app.services.extraction.schemas import EXTRACTION_TOOL_NAME, EXTRACTION_TOOL_SCHEMA


class GeminiExtractionClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMCallError("GEMINI_API_KEY is not configured")
        # Imported lazily, same rationale as the Anthropic client: importable
        # without the SDK being usable/networked (e.g. for schema tests).
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def extract(self, context_prompt: str) -> dict:
        from google.genai import errors, types

        function_declaration = types.FunctionDeclaration(
            name=EXTRACTION_TOOL_NAME,
            description=EXTRACTION_TOOL_SCHEMA["description"],
            parameters_json_schema=EXTRACTION_TOOL_SCHEMA["input_schema"],
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=context_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[types.Tool(function_declarations=[function_declaration])],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY", allowed_function_names=[EXTRACTION_TOOL_NAME]
                        )
                    ),
                ),
            )
        except errors.APIError as e:
            raise LLMCallError(f"Gemini API call failed: {e}") from e

        for call in response.function_calls or []:
            if call.name == EXTRACTION_TOOL_NAME:
                return call.args or {}

        raise LLMCallError("Model did not return the required tool call")
