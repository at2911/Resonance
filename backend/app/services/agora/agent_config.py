"""Default ASR/LLM/TTS configuration for the Agora Conversational AI
agent, built server-side from existing config — never from the frontend,
which would otherwise have to be handed the Gemini API key to embed it
into the LLM block's URL.

Every field below matches the schema verified against current Agora
documentation (direct page fetches, not memory or search-synthesis alone)
before this was written — see docs/AGORA_INTEGRATION.md §3 for the
verification record and confidence labeling per field. In short:

- asr (vendor "ares"): Agora's own native ASR. No external credential —
  confirmed directly on Agora's ARES docs page.
- llm: Google Gemini, reusing this project's own already-verified
  GEMINI_API_KEY and GEMINI_MODEL — confirmed directly on Agora's
  Gemini-as-LLM docs page, including the exact "style": "gemini" field
  and the streamGenerateContent URL shape.
- tts (vendor "minimax", credential_mode "managed"): Agora bills this
  through your Agora account; no MiniMax account/key needed — confirmed
  directly on Agora's MiniMax TTS docs page ("params.key and
  params.group_id are not required" in managed mode).

This combination was chosen specifically because it requires zero new
vendor signups beyond what this project already has configured.
"""

from __future__ import annotations

from app.config import Settings

AGORA_INCIDENT_COMMANDER_SYSTEM_PROMPT = (
    "You are an AI incident commander assisting a human incident response team.\n"
    "Your job is to listen, organize evidence, surface contradictions and missing "
    "information, track decisions and actions, and provide concise spoken status "
    "updates.\n"
    "Never present an unverified hypothesis as a confirmed root cause.\n"
    "Clearly distinguish confirmed facts from hypotheses.\n"
    "Do not invent evidence, owners, timestamps, or causes.\n"
    "Critical operational actions require explicit human approval outside the "
    "voice agent."
)


class AgentConfigError(Exception):
    pass


def build_default_asr_properties() -> dict:
    """Agora's own native ASR — no external credential required."""
    return {"vendor": "ares", "language": "en-US"}


def build_default_llm_properties(settings: Settings) -> dict:
    """Google Gemini as the agent's own conversational LLM. This is a
    separate usage of the same GEMINI_API_KEY from this project's own
    extraction pipeline — Agora calls Gemini directly over HTTP with this
    key embedded in the URL (per the vendor's documented shape); it is
    not routed through our google-genai client or our own reasoning code.
    """
    if not settings.gemini_api_key:
        raise AgentConfigError(
            "GEMINI_API_KEY is not configured — required for the Agora agent's "
            "default LLM (Google Gemini). Configure it, or supply an explicit "
            "llm block in the session-start request."
        )
    model = settings.gemini_model
    return {
        "url": (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:"
            f"streamGenerateContent?alt=sse&key={settings.gemini_api_key}"
        ),
        "style": "gemini",
        "params": {"model": model},
        "system_messages": [
            {"role": "user", "parts": [{"text": AGORA_INCIDENT_COMMANDER_SYSTEM_PROMPT}]}
        ],
    }


def build_default_tts_properties() -> dict:
    """MiniMax via Agora Managed Key — no external MiniMax account/key
    required (Agora bills this through your Agora account)."""
    return {
        "credential_mode": "managed",
        "vendor": "minimax",
        "params": {
            "url": "wss://api.minimax.io/ws/v1/t2a_v2",
            "model": "speech-2.8-turbo",
            "voice_setting": {"voice_id": "English_captivating_female1", "speed": 1.0},
            "audio_setting": {"sample_rate": 44100},
        },
    }


def build_default_agent_properties(settings: Settings) -> dict:
    """Returns {"asr": ..., "llm": ..., "tts": ...} — the three required
    /join blocks session_service.py falls back to when a session-start
    request doesn't supply its own.
    """
    return {
        "asr": build_default_asr_properties(),
        "llm": build_default_llm_properties(settings),
        "tts": build_default_tts_properties(),
    }
