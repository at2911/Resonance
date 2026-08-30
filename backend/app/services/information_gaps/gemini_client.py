"""Gemini equivalent of AnthropicGapAssessmentClient (llm_client.py).
See app/services/extraction/gemini_client.py for the shared rationale;
mirrors it exactly for this engine's tool/schema/prompt.
"""

from __future__ import annotations

from app.services.information_gaps.llm_client import LLMCallError
from app.services.information_gaps.schemas import (
    GAP_ASSESSMENT_TOOL_NAME,
    GAP_ASSESSMENT_TOOL_SCHEMA,
    SYSTEM_PROMPT,
)


class GeminiGapAssessmentClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMCallError("GEMINI_API_KEY is not configured")
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def assess(self, prompt: str) -> dict:
        from google.genai import errors, types

        function_declaration = types.FunctionDeclaration(
            name=GAP_ASSESSMENT_TOOL_NAME,
            description=GAP_ASSESSMENT_TOOL_SCHEMA["description"],
            parameters_json_schema=GAP_ASSESSMENT_TOOL_SCHEMA["input_schema"],
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[types.Tool(function_declarations=[function_declaration])],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY", allowed_function_names=[GAP_ASSESSMENT_TOOL_NAME]
                        )
                    ),
                ),
            )
        except errors.APIError as e:
            raise LLMCallError(f"Gemini API call failed: {e}") from e

        for call in response.function_calls or []:
            if call.name == GAP_ASSESSMENT_TOOL_NAME:
                return call.args or {}

        raise LLMCallError("Model did not return the required tool call")
