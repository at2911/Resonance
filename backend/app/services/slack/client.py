"""Slack call boundary. The only place slack_sdk is touched.

Same shape as the LLM client boundaries: a narrow Protocol so the API layer
can inject a fake in tests, and a real implementation that never claims
success it didn't get. A non-"ok" Slack response or a raised SlackApiError
both surface as SlackCallError — the caller (app/api/slack.py) is
responsible for recording that as a FAILED execution, never a successful
one.
"""

from __future__ import annotations

from typing import Protocol


class SlackCallError(Exception):
    pass


class SlackClient(Protocol):
    def post_message(self, channel: str, text: str) -> dict: ...


class SlackWebClient:
    def __init__(self, bot_token: str) -> None:
        if not bot_token:
            raise SlackCallError("SLACK_BOT_TOKEN is not configured")
        from slack_sdk import WebClient

        self._client = WebClient(token=bot_token)

    def post_message(self, channel: str, text: str) -> dict:
        from slack_sdk.errors import SlackApiError

        try:
            response = self._client.chat_postMessage(channel=channel, text=text)
        except SlackApiError as e:
            error = e.response.get("error") if e.response is not None else str(e)
            raise SlackCallError(f"Slack API call failed: {error}") from e

        if not response.get("ok"):
            raise SlackCallError(f"Slack API returned not-ok: {response.get('error')}")

        return {"ts": response.get("ts"), "channel": response.get("channel")}
