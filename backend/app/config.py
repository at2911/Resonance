"""Configuration loaded strictly from environment variables.

No secret is ever hardcoded. Values default to empty strings so the app can
boot in demo mode without Agora/Slack/LLM credentials configured (those
integrations degrade gracefully and are checked at call time, not at
startup) — see app/services/slack, app/services/agora, app/services/extraction.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    agora_app_id: str = ""
    agora_app_certificate: str = ""
    # REST API (Conversational AI Engine) auth is Basic Auth with a
    # customer key/secret pair — distinct from app_id/app_certificate,
    # which sign RTC tokens for clients joining the channel. See
    # docs/AGORA_INTEGRATION.md §2.
    agora_customer_key: str = ""
    agora_customer_secret: str = ""
    agora_rest_base_url: str = "https://api.agora.io/api/conversational-ai-agent/v2"
    # HMAC secret Agora signs webhook payloads with (Agora-Signature-V2).
    agora_webhook_secret: str = ""

    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5"

    slack_bot_token: str = ""
    slack_channel_id: str = ""

    database_url: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
